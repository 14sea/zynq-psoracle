#!/usr/bin/env python3
"""One open transport, one identity, one epoch — across loader AND runner (S0b).

`docs/pcap_probe_spec.md` §2a names this as S0b: "one `BoardSession` carrying one identity
and one epoch across loader and runner". The snapshot's §5a.3 and §5d.1 are the
requirements; `docs/authority_requirements.md` records why the source repository's module
was not imported. This module is written against those three texts and nothing else.

What is structural here
-----------------------

1. **The port is resolved once, at open, and never again.** The loader in the source
   repository closed the serial port around the ymodem transfer and reopened it, which is
   where "one session" was silently two. `SerialTransport.ymodem_send()` hands the *already
   open* file descriptor to `sb`; the handle is never closed and the symlink is never
   re-resolved between identity and the probe.

2. **Every reply is guarded before it is believed.** A boot banner anywhere in a reply
   means the board restarted under the command; a missing prompt means the reply is
   truncated. Both end the epoch and refuse — there is no "probably fine" path.

3. **No bare CR, ever.** U-Boot repeats the last command on an empty line, and a repeated
   `md` resumes one word past the previous read. The sync is a named no-op (`echo`).

4. **Identity is a fixed constant.** `17A6`, role `verify`, XC7Z010 IDCODE. No flag, no
   environment variable, no argument relaxes it; widening it is a source edit.

5. **A `linux` control plane is refused unconditionally** (spec §3, §5d.4). This session
   knows one control plane, and it is U-Boot.

6. **Capabilities are objects, not strings.** The configuration-read capability and the
   one setup-load capability are module-private instances; a caller that does not hold
   the instance cannot ask for the operation. That is how "a new, named configuration-read
   capability, distinct from `write_sequence()`" (§5d.2) is made checkable.

Nothing in this module performs a devcfg or DMA write; the runner owns the probe script
and this module owns *who may send it*.
"""

from __future__ import annotations

import base64
import contextlib
import fcntl
import hashlib
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

TOOL_VERSION = "board_session.py/0.1.0"

PORT = "/dev/ebaz-uart"
BAUD = 115200
CONTROL_PLANE = "uboot"

# --------------------------------------------------------------- frozen requirements
REQUIRED_BOARDID = "17A6"
REQUIRED_ROLE = "verify"
SLCR_PSS_IDCODE = 0xF8000530
IDCODE_MASK = 0x0FFFFFFF               # bits 31:28 are the silicon revision
REQUIRED_IDCODE = 0x13722093 & IDCODE_MASK

DEVCFG_INT_STS = 0xF800700C
PCFG_DONE = 1 << 2

# --------------------------------------------------------------------- wire format
PROMPT_RE = re.compile(rb"(?P<prompt>zynq-uboot|Zynq)> ?$")
PROMPT_ANY_RE = re.compile(rb"(?P<prompt>zynq-uboot|Zynq)> ")   # anywhere, for mode checks
BOOT_BANNER_RE = re.compile(
    rb"U-Boot SPL|\r?\nU-Boot \d|Trying to boot from|Model: Ebang|"
    rb"Loading Environment from FAT|No ethernet found")
ENV_LINE_RE = re.compile(rb"^([A-Za-z_][A-Za-z0-9_]*)=(.*?)\s*$", re.MULTILINE)
MD_LINE_RE = re.compile(rb"^([0-9a-fA-F]{8}):((?:\s+[0-9a-fA-F]{8}){1,4})", re.MULTILINE)
READY_RE = re.compile(rb"Ready for binary|CC")
# U-Boot pads the label: "## Total Size      = 0x001fcc17 = 2083863 Bytes" (observed on
# 17A6, evidence/s1s3_17A6_2026-08-29-01). A single-space regex consumed a ruling.
YMODEM_SIZE_RE = re.compile(rb"Total Size\s*=\s*(0x[0-9a-fA-F]+)")
SYNC_COMMAND = "echo"

WRITE_CHUNK = 32          # U-Boot echoes with a blocking putc; pace the write
WRITE_GAP_S = 0.002

DISRUPTIONS = frozenset({
    "transport_reopen", "timeout", "uart_disconnect", "prompt_mode_change",
    "soft_reset", "power_cycle", "recovery",
})


class SessionRefusal(Exception):
    """Every non-pass path out of this module. Never caught to continue."""


class _Capability:
    """A token only this module can mint. Holding the instance is the permission."""

    __slots__ = ("name",)

    def __init__(self, name: str):
        self.name = name

    def __repr__(self) -> str:
        return f"<capability {self.name}>"


CONFIG_READ_CAPABILITY = _Capability("configuration-read")   # spec §5d.2
SETUP_LOAD_CAPABILITY = _Capability("setup-load")            # spec §5a.5, the one write


# ------------------------------------------------------------------------- parsing


def preserve(command: str, raw: bytes) -> dict:
    """Every byte that came back, in a form that cannot lose one (raw UART log, §10)."""
    return {"command": command, "byte_count": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "base64": base64.b64encode(raw).decode("ascii"),
            "text": raw.decode("ascii", "replace")}


def parse_env_value(reply: bytes, name: str) -> str:
    """Exactly one assignment of `name`, or a refusal (echoes and stale lines are ambiguity)."""
    matches = [v.decode("ascii", "replace") for k, v in ENV_LINE_RE.findall(reply)
               if k.decode("ascii", "replace") == name]
    if not matches:
        raise SessionRefusal(f"{name} is not set on this board — refused")
    if len(matches) > 1:
        raise SessionRefusal(f"{name} appears {len(matches)} times in one reply — ambiguous")
    value = matches[0].strip()
    if not value:
        raise SessionRefusal(f"{name} is set but empty")
    return value


def parse_md(reply: bytes, addr: int, count: int) -> list[int]:
    """`md.l <addr> <count>` → exactly `count` words at exactly the requested addresses.

    A word count that does not match, a line at an unexpected address, or no lines at all
    is a refusal: an undercount would let a partial buffer be adjudicated as a whole one.
    """
    words: list[int] = []
    expect = addr
    for line_addr, body in MD_LINE_RE.findall(reply):
        if int(line_addr, 16) != expect:
            raise SessionRefusal(
                f"md line at {int(line_addr, 16):#010x}, expected {expect:#010x}")
        vals = [int(w, 16) for w in body.split()]
        words.extend(vals)
        expect += 4 * len(vals)
    if len(words) != count:
        raise SessionRefusal(
            f"md.l {addr:#010x} {count:#x} returned {len(words)} words, not {count}")
    return words


# ---------------------------------------------------------------------- transports


@contextlib.contextmanager
def blocking_fd(fd: int):
    """Clear O_NONBLOCK on `fd` for the duration, restore it after.

    pyserial opens the port O_NONBLOCK and never clears it (its "set blocking" line is
    commented out upstream). `sb` handed that descriptor gets EAGAIN on its reads and
    writes and reports "Timeout on pathname" — which is exactly what the first board run
    under ruling 2026-08-29 produced, after precheck, identity and READY had all passed.
    The flag lives on the open file description, so this changes nothing about WHICH
    port is spoken to: same handle, same session, same epoch (§5d.1).
    """
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags & ~os.O_NONBLOCK)
    try:
        yield fd
    finally:
        fcntl.fcntl(fd, fcntl.F_SETFL, flags)


class SerialTransport:
    """Owns one open serial handle for the whole session; resolved once, never reopened."""

    def __init__(self, port: str = PORT, baud: int = BAUD):
        try:
            import serial  # noqa: PLC0415 — deferred so tests import without pyserial
        except ImportError as exc:  # pragma: no cover
            raise SessionRefusal("pyserial is required for board sessions") from exc
        self.requested_port = port
        self.resolved_port = os.path.realpath(port)
        try:
            stat = os.stat(self.resolved_port)
        except OSError as exc:
            raise SessionRefusal(f"cannot stat {port}: {exc}") from exc
        self.device_id = f"{os.major(stat.st_rdev)}:{os.minor(stat.st_rdev)}"
        self._serial = serial.Serial(self.resolved_port, baud, timeout=0.1)

    def _read_until(self, pattern: re.Pattern, timeout: float) -> bytes:
        buf, t0 = b"", time.monotonic()
        while time.monotonic() - t0 < timeout:
            chunk = self._serial.read(512)
            if chunk:
                buf += chunk
                if pattern.search(buf):
                    break
        return buf

    def drain(self) -> bytes:
        """Everything the board sent since the last read. Returned, never discarded:
        a boot banner sitting in the receive buffer is the evidence of a reboot."""
        pending = b""
        while True:
            chunk = self._serial.read(4096)
            if not chunk:
                return pending
            pending += chunk

    def send_line(self, line: str) -> None:
        data = line.encode("ascii") + b"\r"
        for start in range(0, len(data), WRITE_CHUNK):
            self._serial.write(data[start:start + WRITE_CHUNK])
            if len(data) > WRITE_CHUNK:
                time.sleep(WRITE_GAP_S)

    def read_until(self, pattern: re.Pattern, timeout: float) -> bytes:
        return self._read_until(pattern, timeout)

    def command(self, line: str, timeout: float) -> bytes:
        self.send_line(line)
        return self._read_until(PROMPT_RE, timeout)

    def ymodem_send(self, path: Path, log: Path, timeout: float) -> None:
        """`sb -k` over THIS handle's descriptor. The port is not closed or reopened."""
        fd = self._serial.fileno()
        with open(log, "wb") as logf, blocking_fd(fd):
            try:
                rc = subprocess.run(["sb", "-k", str(path)], stdin=fd, stdout=fd,
                                    stderr=logf, check=False, timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                raise SessionRefusal(f"sb did not finish within {timeout} s") from exc
        if rc.returncode != 0:
            raise SessionRefusal(f"sb failed rc={rc.returncode} (see {log})")

    def descriptor(self) -> dict:
        return {"requested_port": self.requested_port, "resolved_port": self.resolved_port,
                "device_id": self.device_id}

    def close(self) -> None:
        self._serial.close()


# ------------------------------------------------------------------------ the session


class BoardSession:
    """One transport, one identity, one epoch, one plmark — and nothing without all of them."""

    def __init__(self, transport):
        self.transport = transport
        self.epoch = 0
        self.disruptions: list[dict] = []
        self.log: list[dict] = []          # every command and reply, preserved (§10)
        self.rereads: list[dict] = []      # md.l replies that had to be re-read (transport)
        self._identity: dict | None = None
        self._prompt_mode: str | None = None
        self.plmark: str | None = None
        self.setup_load: dict | None = None

    # -- epoch ------------------------------------------------------------------

    def note_disruption(self, kind: str, detail: str = "") -> int:
        if kind not in DISRUPTIONS:
            raise SessionRefusal(f"unknown disruption {kind!r}; one of {sorted(DISRUPTIONS)}")
        self.epoch += 1
        self._identity = None
        self.plmark = None
        self.disruptions.append({"epoch_ended": self.epoch - 1, "kind": kind,
                                 "detail": detail, "at": time.time()})
        return self.epoch

    # -- the guarded command ----------------------------------------------------

    def command(self, line: str, timeout: float = 1.5) -> bytes:
        """Send one named command; refuse an empty line; guard the reply before returning."""
        if not line.strip():
            raise SessionRefusal("an empty line repeats U-Boot's last command; refused")
        self._inspect_pending(f"before {line!r}")
        raw = self.transport.command(line, timeout)
        self.log.append(preserve(line, raw))
        return self._guard(line, raw)

    def _inspect_pending(self, where: str) -> bytes:
        """Unsolicited bytes are read and judged, never discarded (a banner is a reboot,
        a prompt of the other kind is a control-plane change)."""
        pending = self.transport.drain()
        if pending:
            self.log.append(preserve(f"<unsolicited {where}>", pending))
            self._check_banner(pending, f"pending {where}")
            self._check_prompt_mode(pending, f"pending {where}")
        return pending

    def _check_banner(self, raw: bytes, where: str) -> None:
        if BOOT_BANNER_RE.search(raw):
            self.note_disruption("soft_reset", f"boot banner {where}")
            raise SessionRefusal(f"the board restarted ({where})")

    def _check_prompt_mode(self, raw: bytes, where: str) -> None:
        """Every prompt seen anywhere — reply, pending bytes, READY line — must be the
        same kind as the first one; anything else is a different board or firmware."""
        for m in PROMPT_ANY_RE.finditer(raw):
            prompt = m.group("prompt").decode("ascii")
            if self._prompt_mode is None:
                self._prompt_mode = prompt
            elif prompt != self._prompt_mode:
                previous, self._prompt_mode = self._prompt_mode, prompt
                self.note_disruption("prompt_mode_change", f"{previous!r} -> {prompt!r} {where}")
                raise SessionRefusal(f"the prompt changed from {previous!r} to {prompt!r} ({where})")

    def _guard(self, line: str, raw: bytes) -> bytes:
        self._check_banner(raw, f"in the reply to {line!r}")
        if not PROMPT_RE.search(raw):
            self.note_disruption("timeout", f"no prompt after {line!r}")
            raise SessionRefusal(f"no U-Boot prompt after {line!r}: {raw[-80:]!r}")
        self._check_prompt_mode(raw, f"in the reply to {line!r}")
        return raw

    def sync(self) -> bytes:
        return self.command(SYNC_COMMAND, 2.0)

    def read_words(self, addr: int, count: int, timeout: float = 3.0) -> list[int]:
        return self.read_command(f"md.l {addr:#010x} {count:#x}", addr, count, timeout)

    MD_REREADS = 2      # evidence/p2_17A6_2026-08-29-01: one dropped line in 32 readouts

    def read_command(self, cmd: str, addr: int, count: int, timeout: float = 3.0,
                     rereads: int = MD_REREADS) -> list[int]:
        """Send an `md.l` line exactly as given (the plan's text, not a reformatting).

        A malformed reply (line address or word count wrong) is a console-transport fault,
        not an observation: the identical `md.l` may be re-sent up to `rereads` times. This
        is a memory read of DDR — no DMA is re-issued, nothing is written — so it is not a
        retry in §7.4's sense. Every raw reply stays in the log; the count is recorded.
        """
        if not cmd.startswith("md.l "):
            raise SessionRefusal("read_command is for md.l only")
        attempts = 0
        while True:
            attempts += 1
            # The transport step is NOT inside the try: a banner, a prompt-mode change or a
            # missing prompt is a session refusal that has already ended the epoch, and it
            # must propagate — never be answered with another md.l (owner review of ca94fed).
            raw = self.command(cmd, timeout)
            try:
                words = parse_md(raw, addr, count)
            except SessionRefusal as malformed:
                if attempts > rereads:
                    raise SessionRefusal(f"{malformed} (after {attempts} attempts)") from None
                continue
            if attempts > 1:
                self.rereads.append({"command": cmd, "attempts": attempts})
            return words

    def read_word(self, addr: int) -> int:
        return self.read_words(addr, 1)[0]

    # -- identity ---------------------------------------------------------------

    def verify_identity(self) -> dict:
        """§5a.3 / §5b.1: boardid, role and IDCODE on THIS session, in THIS epoch."""
        started = time.time()
        findings: list[str] = []
        boardid = parse_env_value(self.command("printenv boardid"), "boardid")
        role = parse_env_value(self.command("printenv role"), "role")
        idcode = self.read_word(SLCR_PSS_IDCODE)
        if boardid != REQUIRED_BOARDID:
            findings.append(f"boardid {boardid!r} != {REQUIRED_BOARDID!r}")
        if role != REQUIRED_ROLE:
            findings.append(f"role {role!r} != {REQUIRED_ROLE!r}")
        if idcode & IDCODE_MASK != REQUIRED_IDCODE:
            findings.append(f"PSS_IDCODE {idcode:#010x} is not XC7Z010")
        identity = {
            "tool": TOOL_VERSION,
            "transport": self.transport.descriptor(),
            "parsed": {"boardid": boardid, "role": role, "pss_idcode": f"{idcode:#010x}"},
            "requirements": {"boardid": REQUIRED_BOARDID, "role": REQUIRED_ROLE,
                             "idcode_masked": f"{REQUIRED_IDCODE:#010x}"},
            "control_plane": CONTROL_PLANE,
            "epoch": self.epoch,
            "elapsed_s": round(time.time() - started, 3),
            "findings": findings,
        }
        if findings:
            self._identity = None
            raise SessionRefusal("board identity refused: " + "; ".join(findings))
        self._identity = identity
        return identity

    @property
    def identity(self) -> dict | None:
        return self._identity

    # -- the interlock ----------------------------------------------------------

    def authorise(self, capability: _Capability, control_plane: str = CONTROL_PLANE) -> dict:
        """The only door to a device operation: this capability, this session, this epoch."""
        if not isinstance(capability, _Capability):
            raise SessionRefusal("a capability instance is required, not a name")
        if control_plane != CONTROL_PLANE:
            raise SessionRefusal(
                f"control plane {control_plane!r} is refused; this session is U-Boot only")
        if self._identity is None:
            raise SessionRefusal("no verified identity on this session")
        if self._identity["epoch"] != self.epoch:
            raise SessionRefusal(
                f"identity is from epoch {self._identity['epoch']}, session is in "
                f"epoch {self.epoch} — re-verify")
        return self._identity

    def check_plmark(self) -> str:
        """§5a.6: the same plmark at every stage; a reboot ends the probe."""
        if self.plmark is None:
            raise SessionRefusal("no plmark on this session — no setup load in this epoch")
        seen = parse_env_value(self.command("printenv plmark"), "plmark")
        if seen != self.plmark:
            self.note_disruption("power_cycle", f"plmark {self.plmark} -> {seen}")
            raise SessionRefusal("plmark changed — not the boot that configured the PL")
        return seen

    # -- ymodem, guarded, on the session's own transport -------------------------

    def begin_ymodem(self, load_addr: int) -> bytes:
        """`loady` answers with READY, not a prompt, so it cannot go through `command()`;
        it still goes through the same pending-bytes and banner guards."""
        self._inspect_pending("before loady")
        line = f"loady {load_addr:#010x}"
        self.transport.send_line(line)
        raw = self.transport.read_until(READY_RE, 6.0)
        self.log.append(preserve(line, raw))
        self._check_banner(raw, "instead of READY")
        self._check_prompt_mode(raw, "in the loady reply")
        if not READY_RE.search(raw):
            self.note_disruption("timeout", "loady did not become ready")
            raise SessionRefusal("loady did not become ready for ymodem")
        return raw

    def finish_ymodem(self, path: Path, log_path: Path, size: int,
                      timeout: float = 600.0) -> bytes:
        self.transport.ymodem_send(path, log_path, timeout)
        tail = self.transport.read_until(PROMPT_RE, 20.0)
        self.log.append(preserve("sb -k", tail))
        self._guard("ymodem", tail)
        m = YMODEM_SIZE_RE.search(tail)
        if not m:
            raise SessionRefusal("U-Boot did not report the transferred size")
        reported = int(m.group(1), 16)
        if reported != size:
            raise SessionRefusal(f"U-Boot received {reported} bytes, the file is {size}")
        return tail

    # -- the one configuration write (§5a.4–5) -----------------------------------

    def load_carrier(self, capability: _Capability, bit_path: Path, expected_sha256: str,
                     log_path: Path, load_addr: int = 0x04000000) -> dict:
        """The session's single configuration write, on the verified identity's session."""
        if capability is not SETUP_LOAD_CAPABILITY:
            raise SessionRefusal("the setup load needs SETUP_LOAD_CAPABILITY")
        identity = self.authorise(capability)
        if shutil.which("sb") is None:
            raise SessionRefusal("`sb` (lrzsz) is not installed; refused before any command")
        data = bit_path.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        if sha != expected_sha256:
            raise SessionRefusal(f"bitstream sha256 {sha} != pinned {expected_sha256}")
        before = self.read_word(DEVCFG_INT_STS)
        if before & PCFG_DONE:
            raise SessionRefusal(
                f"the PL is already configured (INT_STS={before:#010x}); power-cycle first")
        size = len(data)
        # loady -> ymodem on the SAME handle -> prompt, size verified
        self.begin_ymodem(load_addr)
        self.finish_ymodem(bit_path, log_path, size)
        # clear the sticky PCFG_DONE so the post-load check is an edge
        self.command(f"mw.l {DEVCFG_INT_STS:#010x} {PCFG_DONE:#010x} 1")
        cleared = self.read_word(DEVCFG_INT_STS)
        if cleared & PCFG_DONE:
            raise SessionRefusal(f"PCFG_DONE did not clear (INT_STS={cleared:#010x})")
        self.command(f"fpga loadb 0 {load_addr:#010x} {size:#010x}", 30.0)
        after = self.read_word(DEVCFG_INT_STS)
        if not after & PCFG_DONE:
            raise SessionRefusal(
                f"configuration did not happen: INT_STS={after:#010x}, PCFG_DONE clear")
        marker = f"{time.time_ns():016x}"
        self.command(f"setenv plmark {marker}")
        self.plmark = marker
        self.setup_load = {
            "bitstream": str(bit_path), "sha256": sha, "bytes": size,
            "load_addr": f"{load_addr:#010x}", "int_sts_before": f"{before:#010x}",
            "int_sts_cleared": f"{cleared:#010x}", "int_sts_after": f"{after:#010x}",
            "plmark": marker, "epoch": self.epoch, "boardid": identity["parsed"]["boardid"],
        }
        return self.setup_load
