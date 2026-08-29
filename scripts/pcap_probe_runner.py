#!/usr/bin/env python3
"""The S1–S3 probe runner — S0b of `docs/pcap_probe_spec.md`. Executes ONLY under a ruling.

Host-only until a whole-of-probe board ruling exists (spec §2). Without a ruling file the
runner refuses before it opens a port; on any stop it marks the ruling consumed, and a
consumed ruling is refused (spec §2: "any failure … consumes the ruling").

The runner does not invent a sequence. It executes the plan `pcap_probe_plan.build_plan()`
produces — the same plan the planner's guards adjudicate — and adds only the reads the
specification names outside the plan (`printenv plmark`, `dcache`, the sync). Every other
command it could send is refused by `RUNNER_EXTRA_COMMANDS`.

Verdicts are §7's fixed vocabulary and nothing else. Adjudication is a pure function so
that it is tested against constructed buffers, not against a board.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import bitstream_frames as bf  # noqa: E402
import board_session as bsn  # noqa: E402
import pcap_probe_plan as pp  # noqa: E402

TOOL_VERSION = "pcap_probe_runner.py/0.1.0"

# ------------------------------------------------------------------ pinned constants
CARRIER_BIT = REPO_ROOT / "gate_runs/claimb_round1_carrier_2026_08_13_erratum006/carrier.bit"
CARRIER_SHA256 = "8c3369e8e4755da5aceeb7844690d5e132b2e65647004c0a46c0e868e34f0b8a"
TARGET_FAR = 0x00000B99                     # spec §3 / snapshot §4
TARGET_SHA256 = "9029c9d032e0287453cb5c02cd18be42bc03acef38b17ef7295ee0d16beb6b1f"
# S2 expectations are constants (snapshot §4b), not run-time computations; the table is
# checked against them at load and they are never re-derived on the board.
S2_EXPECTED = {
    0x00000B98: "09e6542e15d2236ef806ab934ff70db967cde6d248bda996b753d6542839351c",
    0x00000B9A: "80f782b962888a97d6a663d116d3b6158ff4d7408626ce6b83f43ba855356477",
}
S2_FARS = tuple(S2_EXPECTED)
S3_TRANSACTIONS = 10
SENTINEL = 0xA5A5A5A5

# fresh-power preconditions (snapshot §5a.2), values recorded on 17A6
PRECHECK_REGS = (
    ("devcfg CTRL", 0xF8007000, 0x4E00E07F),
    ("devcfg INT_STS", 0xF800700C, 0xA802000B),
    ("devcfg STATUS", 0xF8007014, 0x40000A30),
    ("SLCR FPGA0_CLK_CTRL", 0xF8000170, 0x00400800),
)

VERDICTS = ("BUFFER_UNCHANGED_FROM_PREFILL", "SENTINEL_REMAINS", "PASS", "BLANK",
            "MISADDRESS", "MISADDRESS_AMBIGUOUS", "NO_MATCH", "OVERFLOW", "TIMEOUT")

# `OVERFLOW` is one bit. Every other error bit is a generic DMA/AXI error with no pinned
# mechanism: it stops with `verdict: null` and its raw bit names (line_plan R3).
INT_STS_RX_FIFO_OV = 1 << 18
INT_STS_ERROR_NAMES = {23: "AXI_WTO", 22: "AXI_WERR", 21: "AXI_RTO", 20: "AXI_RERR",
                       18: "RX_FIFO_OV", 15: "DMA_CMD_ERR", 14: "DMA_Q_OV",
                       11: "P2D_LEN_ERR", 6: "PCFG_HMAC_ERR"}

# the only commands the runner sends that are not in the plan; all read-only
RUNNER_EXTRA_COMMANDS = frozenset({"printenv plmark", "dcache", bsn.SYNC_COMMAND})

RULING_REQUIRED_FIELDS = ("ruling", "boardid", "granted_by", "date")
RULING_TEXT = "whole-of-probe S1-S3"


PRECONDITION = "PRECONDITION"   # not a verdict: a gate refused before any payload existed
DMA_ERROR = "DMA_ERROR"         # not a verdict: a generic error bit with no pinned mechanism


class ProbeStop(Exception):
    """A §7 stop. `verdict` is one of VERDICTS, or PRECONDITION for a gate that refused.

    The distinction is `line_plan.md` R3: a precondition stop (CTRL mask, loopback bit,
    PCFG_DONE clear, sentinel not present, stale status) is a non-discriminating
    observation. It ends the line under the stop-loss and says nothing about the silicon.
    """

    def __init__(self, verdict: str, detail: str, record: dict | None = None):
        super().__init__(f"{verdict}: {detail}")
        self.verdict, self.detail, self.record = verdict, detail, record


# ------------------------------------------------------------------ frame table


def frame_sha256(words: list[int]) -> str:
    return hashlib.sha256(struct.pack(f">{len(words)}I", *words)).hexdigest()


def load_frame_table(bit_path: Path = CARRIER_BIT) -> dict:
    """{FAR: words}, the reverse index, and the table digest — frozen from the carrier."""
    data = bit_path.read_bytes()
    if hashlib.sha256(data).hexdigest() != CARRIER_SHA256:
        raise ProbeStop("NO_MATCH", "the carrier bitstream does not hash to the pinned value")
    frames = bf.parse_frames(bit_path)["frames"]
    reverse: dict[str, list[int]] = {}
    for far, words in frames.items():
        reverse.setdefault(frame_sha256(words), []).append(far)
    for far, pinned in {TARGET_FAR: TARGET_SHA256, **S2_EXPECTED}.items():
        got = frame_sha256(frames[far])
        if got != pinned:
            raise ProbeStop("NO_MATCH", f"frame table {far:#010x} hashes to {got}, pinned {pinned}")
    return {"frames": frames, "reverse": reverse}


# ------------------------------------------------------------------ adjudication (§7)


def adjudicate(words: list[int], sentinel: int, expected_sha256: str,
               reverse: dict[str, list[int]]) -> dict:
    """§7.3, both steps, on a 202-word buffer. Pure; no board, no I/O."""
    if len(words) != pp.READBACK_WORDS:
        raise ValueError(f"adjudication needs {pp.READBACK_WORDS} words, got {len(words)}")
    survivors = sum(1 for w in words if w == sentinel)
    lo, hi = pp.FRAME_WORDS, 2 * pp.FRAME_WORDS
    frame = words[lo:hi]
    pad = words[:lo]
    out = {"sentinel_words_surviving": survivors,
           "pad_sha256": frame_sha256(pad), "frame_sha256": frame_sha256(frame),
           "adjudicated_slice": [lo, hi], "verdict": None, "detail": None}
    # step 1 — the whole buffer
    if survivors == len(words):
        out.update(verdict="BUFFER_UNCHANGED_FROM_PREFILL",
                   detail="instrument unvalidated; not a statement that the DMA never wrote")
        return out
    if survivors:
        out.update(verdict="SENTINEL_REMAINS",
                   detail="instrument unvalidated; partial transfer or value collision")
        return out
    # step 2 — the frame half only, first row that matches wins
    if out["frame_sha256"] == expected_sha256:
        out.update(verdict="PASS", detail="bit-exact against the pinned target hash")
        return out
    if all(w == 0 for w in frame):
        out.update(verdict="BLANK",
                   detail="the DMA replaced the destination with zeros; read-path zeros and a "
                          "misaddress to a blank FAR are indistinguishable in these bytes")
        return out
    hits = reverse.get(out["frame_sha256"], [])
    if len(hits) == 1:
        out.update(verdict="MISADDRESS", detail=f"matches FAR {hits[0]:#010x}",
                   matched_far=f"{hits[0]:#010x}")
        return out
    if len(hits) > 1:
        out.update(verdict="MISADDRESS_AMBIGUOUS",
                   detail=f"matches {len(hits)} FARs; no pick is made",
                   candidate_fars=[f"{h:#010x}" for h in sorted(hits)])
        return out
    out.update(verdict="NO_MATCH", detail="no frame in the table has this hash")
    return out


# ------------------------------------------------------------------ ruling (§2)


def check_ruling(path: Path, text: str = RULING_TEXT) -> dict:
    """A whole-of-probe ruling is a file with fixed fields; consumed once, never reused.
    `text` is the ruling this runner needs: an S1–S3 ruling does not authorise P1 and
    vice versa."""
    consumed = path.with_name(path.name + ".consumed")
    if consumed.exists():
        raise bsn.SessionRefusal(f"the ruling {path} was consumed ({consumed.read_text().strip()})")
    ruling = _parse_ruling(path, text)
    ruling["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return ruling


def _parse_ruling(path: Path, text: str = RULING_TEXT) -> dict:
    try:
        ruling = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise bsn.SessionRefusal(f"no readable ruling at {path}: {exc}") from exc
    missing = [f for f in RULING_REQUIRED_FIELDS if not ruling.get(f)]
    if missing:
        raise bsn.SessionRefusal(f"ruling lacks {missing}")
    if ruling["ruling"] != text:
        raise bsn.SessionRefusal(f"ruling text {ruling['ruling']!r} != {text!r}")
    if ruling["boardid"] != bsn.REQUIRED_BOARDID:
        raise bsn.SessionRefusal(f"ruling names board {ruling['boardid']!r}")
    return ruling


def claim_ruling(path: Path) -> Path:
    """Consume the ruling atomically BEFORE the port is opened. One ruling, one attempt:
    PASS, stop, crash and a concurrent runner all leave it consumed."""
    consumed = path.with_name(path.name + ".consumed")
    try:
        fd = os.open(consumed, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        raise bsn.SessionRefusal(f"the ruling {path} is already claimed") from None
    with os.fdopen(fd, "w") as f:
        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} claimed pid={os.getpid()}\n")
    return consumed


def record_outcome(consumed: Path, why: str) -> None:
    with open(consumed, "a") as f:
        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {why}\n")


# ------------------------------------------------------------------ precheck (§5a.2)


def precheck(session: bsn.BoardSession) -> dict:
    """Read-only, all preconditions, every reply guarded by the session. Refuses, never repairs."""
    checks, problems = [], []
    session.sync()
    for name, addr, want in PRECHECK_REGS:
        got = session.read_word(addr)
        entry = {"check": name, "address": f"{addr:#010x}", "expected": f"{want:#010x}",
                 "observed": f"{got:#010x}", "passed": got == want}
        if got != want:
            problems.append(f"{name} = {got:#010x} != {want:#010x}")
        if addr == bsn.DEVCFG_INT_STS and got & bsn.PCFG_DONE:
            problems.append("PCFG_DONE=1 — the PL is still configured")
        checks.append(entry)
    raw = session.command("printenv plmark")
    undefined = b"not defined" in raw
    defined = bsn.ENV_LINE_RE.findall(raw)
    if any(k == b"plmark" for k, _ in defined):
        problems.append("plmark is defined — not a fresh power-on")
    elif not undefined:
        problems.append("the plmark reply is neither a marker nor 'not defined'")
    checks.append({"check": "plmark undefined", "passed": undefined and not defined})
    record = {"checks": checks, "problems": problems, "passed": not problems}
    if problems:
        raise bsn.SessionRefusal("precheck refused: " + "; ".join(problems))
    return record


# ------------------------------------------------------------------ one plan (§5b, §5d)


def _stop(stage: dict, verdict: str, detail: str) -> ProbeStop:
    if verdict in (PRECONDITION, DMA_ERROR):
        stage["verdict"], stage["stop"], stage["detail"] = None, verdict, detail
    else:
        stage["verdict"], stage["detail"] = verdict, detail
    return ProbeStop(verdict, detail, stage)


def validate_plan(plan: dict) -> None:
    """Re-adjudicate the plan that is about to be sent with the planner's own guards, then
    require it to be IDENTICAL to what the planner builds for the same inputs.

    A plan is data; the runner must not trust that it came from `build_plan` untouched.
    The guards catch an illegal command; the equality catches everything else — an error
    mask zeroed, a timeout stretched, a CTRL requirement relaxed — without the runner
    having to know which fields are safety-relevant (review round 2, item 1)."""
    canonical = pp.build_plan(plan["target_far"], plan["dma_order"], plan["sentinel"])
    if plan != canonical:
        diverging = sorted(k for k in set(plan) | set(canonical)
                           if plan.get(k) != canonical.get(k))
        raise ValueError(f"plan differs from the planner's canonical output in {diverging}")
    pp.check_allowlist(plan)
    pp.check_value_policy(plan)
    pp.check_dma_transactions(plan)
    pp.check_schedule(plan)
    phases = pp.command_buffer_phases(plan)
    if len(phases) != 2:
        raise ValueError(f"expected a readback stream and a cleanup stream, got {len(phases)}")
    pp.validate_readback_stream(phases[0], plan["target_far"])
    pp.validate_cleanup_stream(phases[1])
    if plan["sentinel"] != SENTINEL:
        raise ValueError(f"sentinel {plan['sentinel']:#010x} is not the pinned {SENTINEL:#010x}")


def error_bit_names(value: int) -> list[str]:
    return [name for bit, name in sorted(INT_STS_ERROR_NAMES.items(), reverse=True)
            if value & (1 << bit)]


class _Sender:
    """Every line the runner sends goes through here; anything outside the validated plan
    or the named read-only extras is refused before it reaches the transport."""

    def __init__(self, session: bsn.BoardSession, plan: dict):
        self.session = session
        self.allowed = {s["cmd"] for s in plan["uboot_script"]} | RUNNER_EXTRA_COMMANDS

    def __call__(self, cmd: str, timeout: float = 3.0) -> bytes:
        if cmd not in self.allowed:
            raise bsn.SessionRefusal(f"command not in the validated plan: {cmd!r}")
        return self.session.command(cmd, timeout)

    def words(self, cmd: str, addr: int, count: int) -> list[int]:
        if cmd not in self.allowed:
            raise bsn.SessionRefusal(f"command not in the validated plan: {cmd!r}")
        return self.session.read_command(cmd, addr, count)     # md.l only; re-read policy §2b


def execute_plan(capability, session: bsn.BoardSession, plan: dict, table: dict,
                 expected_sha256: str, stage_name: str) -> dict:
    """Send the plan's commands in order; gate each reply; adjudicate the readout.

    The plan is what the planner's guards adjudicated; this function adds no memory
    command. The only repetition it permits is re-reading `INT_STS` while waiting for a
    completion, which is a non-destructive read and is counted in the record.
    """
    if capability is not bsn.CONFIG_READ_CAPABILITY:
        raise bsn.SessionRefusal("execute_plan needs CONFIG_READ_CAPABILITY")
    validate_plan(plan)
    send = _Sender(session, plan)
    identity = session.authorise(capability)
    plmark = session.check_plmark()
    stage = {
        "tool": TOOL_VERSION, "stage": stage_name, "schema": "zynq-psmap/stage_record/1",
        "identity": identity, "epoch": session.epoch, "plmark": plmark,
        "plan": {k: plan[k] for k in ("target_far", "dma_order", "sentinel", "timeout_s",
                                      "timeout_basis", "ctrl_mask", "ctrl_required",
                                      "int_sts_error_mask", "int_sts_clear_mask",
                                      "command_words", "cleanup_words", "adjudicated_slice")},
        "expected": {"target_far": f"{plan['target_far']:#010x}",
                     "frame_sha256": expected_sha256},
        "observations": {}, "waits": [], "readout": None, "verdict": None, "stop": None,
        "detail": None,
        "started": time.time(),
    }
    obs = stage["observations"]
    clear_mask, err_mask = plan["int_sts_clear_mask"], plan["int_sts_error_mask"]
    pending_stop: ProbeStop | None = None     # a payload verdict waits for the cleanup
    rereads_before = len(session.rereads)

    for step in plan["uboot_script"]:
        name, cmd = step["step"], step["cmd"]
        form, start, span = pp.parse_command(cmd)
        if form == "dcache-off":
            send(cmd)
            reply = send("dcache").decode("ascii", "replace")
            obs["dcache"] = reply
            if "Cache is OFF" not in reply:
                raise _stop(stage, PRECONDITION,
                            f"D-cache is not off after `dcache off`: {reply.strip()!r}")
            continue
        if form == "mw.l":
            send(cmd)
            if name.startswith("dma-") and start == pp.REG["DMA_DEST_LEN"]:
                stage["waits"].append({"command": name, "queued_at": time.monotonic()})
            continue
        # md.l — read, then gate by the plan's own step name
        count = span // 4
        if name.startswith("wait-"):
            wait = stage["waits"][-1]
            deadline = wait["queued_at"] + plan["timeout_s"]
            polls = 0
            while True:
                value = send.words(cmd, start, 1)[0]
                polls += 1
                if value & err_mask:
                    wait.update(int_sts=f"{value:#010x}", polls=polls,
                                error_bits=error_bit_names(value))
                    if value & INT_STS_RX_FIFO_OV:
                        raise _stop(stage, "OVERFLOW",
                                    f"{name}: RX_FIFO_OV (INT_STS {value:#010x})")
                    raise _stop(stage, DMA_ERROR,
                                f"{name}: INT_STS {value:#010x} error bits "
                                f"{error_bit_names(value)}; no mechanism is pinned")
                if value & pp.INT_STS_D_P_DONE:
                    wait.update(int_sts=f"{value:#010x}", polls=polls,
                                elapsed_s=round(time.monotonic() - wait["queued_at"], 6),
                                elapsed_basis="measured")
                    break
                if time.monotonic() > deadline:
                    wait.update(int_sts=f"{value:#010x}", polls=polls)
                    raise _stop(stage, "TIMEOUT",
                                f"{name}: no D_P_DONE within {plan['timeout_s']} s "
                                f"(INT_STS {value:#010x})")
            continue
        words = send.words(cmd, start, count)
        if name == "ctrl-gate":
            obs["ctrl"] = f"{words[0]:#010x}"
            if words[0] & plan["ctrl_mask"] != plan["ctrl_required"]:
                raise _stop(stage, PRECONDITION,
                            f"CTRL {words[0]:#010x} fails the masked gate "
                            f"({plan['ctrl_mask']:#010x} -> {plan['ctrl_required']:#010x})")
            obs["ctrl_full_word_matches_historical"] = words[0] == 0x4E00E07F
        elif name == "loopback-gate":
            obs["mctrl"] = f"{words[0]:#010x}"
            if words[0] & pp.MCTRL_PCAP_LPBK:
                raise _stop(stage, PRECONDITION,
                            f"MCTRL {words[0]:#010x} has PCAP_LPBK set; STOP before any DMA")
        elif name == "pcfg-done":
            obs["int_sts_initial"] = f"{words[0]:#010x}"
            if not words[0] & pp.INT_STS_PCFG_DONE:
                raise _stop(stage, PRECONDITION,
                            f"INT_STS {words[0]:#010x}: PCFG_DONE clear, readback forbidden")
        elif name == "sentinel-verify":
            if any(w != plan["sentinel"] for w in words):
                raise _stop(stage, PRECONDITION,
                            "sentinel not confirmed present before the read (§7.5)")
        elif name.startswith("clear-verify-"):
            if words[0] & clear_mask:
                raise _stop(stage, PRECONDITION,
                            f"{name}: INT_STS {words[0]:#010x} did not clear "
                            f"({words[0] & clear_mask:#010x} remains)")
        elif name == "readout":
            stage["readout"] = [f"{w:#010x}" for w in words]
            stage.update(adjudicate(words, plan["sentinel"], expected_sha256, table["reverse"]))
            if stage["verdict"] != "PASS":
                # §5d.5: the engine is still cleaned up (DESYNC) and the final status
                # recorded; the stop is raised after the plan's last step.
                pending_stop = ProbeStop(stage["verdict"], stage["detail"], stage)
        elif name == "status-final":
            obs["int_sts_final"] = f"{words[0]:#010x}"
        else:
            raise bsn.SessionRefusal(f"the plan has a read this runner does not gate: {name}")
    stage["elapsed_s"] = round(time.time() - stage["started"], 3)
    stage["transport_rereads"] = [r for r in session.rereads[rereads_before:]]
    if pending_stop is not None:
        raise pending_stop
    return stage


# ------------------------------------------------------------------ the chain (§8)


def write_record(out_dir: Path, name: str, record: dict) -> Path:
    path = out_dir / f"{name}.json"
    partial = path.with_name(path.name + ".part")
    partial.write_text(json.dumps(record, indent=2, default=str) + "\n", encoding="utf-8")
    os.replace(partial, path)
    return path


def run_probe(session: bsn.BoardSession, out_dir: Path, ruling: dict,
              table: dict | None = None, bit_path: Path = CARRIER_BIT) -> dict:
    """Precheck → identity → setup load → S1 → S2 → S3, one boot, one epoch, one ruling."""
    table = table or load_frame_table(bit_path)
    summary = {"tool": TOOL_VERSION, "ruling": ruling, "stages": {}, "outcome": None}

    def finish(stage_record: dict | None, name: str):
        if stage_record is not None:
            write_record(out_dir, name, stage_record)
            summary["stages"][name] = stage_record.get("verdict")

    try:
        summary["precheck"] = precheck(session)
        summary["identity"] = session.verify_identity()
        summary["setup_load"] = session.load_carrier(
            bsn.SETUP_LOAD_CAPABILITY, bit_path, CARRIER_SHA256, out_dir / "ymodem.log")
        # S1 — one readback of the target
        plan = pp.build_plan(TARGET_FAR, pp.PINNED_DMA_ORDER, SENTINEL)
        finish(execute_plan(bsn.CONFIG_READ_CAPABILITY, session, plan, table,
                            TARGET_SHA256, "S1"), "S1")
        # S2 — each neighbour must equal ITS OWN pinned hash
        for i, far in enumerate(S2_FARS):
            plan = pp.build_plan(far, pp.PINNED_DMA_ORDER, SENTINEL)
            finish(execute_plan(bsn.CONFIG_READ_CAPABILITY, session, plan, table,
                                S2_EXPECTED[far], f"S2_{i}"), f"S2_{i}")
        # S3 — ten independent transactions, all equal to the target AND to each other
        hashes = []
        for i in range(S3_TRANSACTIONS):
            plan = pp.build_plan(TARGET_FAR, pp.PINNED_DMA_ORDER, SENTINEL)
            rec = execute_plan(bsn.CONFIG_READ_CAPABILITY, session, plan, table,
                               TARGET_SHA256, f"S3_{i}")
            finish(rec, f"S3_{i}")
            hashes.append(rec["frame_sha256"])
        if len(set(hashes)) != 1 or hashes[0] != TARGET_SHA256:
            raise ProbeStop("NO_MATCH", "S3: the ten reads are not identical to the target")
        summary["outcome"] = "PASS"
    except ProbeStop as stop:
        finish(stop.record, stop.record["stage"] if stop.record else "stop")
        summary["outcome"] = f"STOP {stop.verdict}: {stop.detail}"
    except bsn.SessionRefusal as refusal:
        summary["outcome"] = f"REFUSED: {refusal}"
    finally:
        summary["uart_log"] = session.log
        summary["disruptions"] = session.disruptions
        summary["transport_rereads"] = session.rereads
        summary["epoch_final"] = session.epoch
        write_record(out_dir, "summary", summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ruling", type=Path, required=True,
                    help="the whole-of-probe board ruling file (spec §2); consumed on any stop")
    ap.add_argument("--out", type=Path, required=True,
                    help="evidence directory; refused if it exists")
    ap.add_argument("--port", default=bsn.PORT)
    args = ap.parse_args(argv)

    # host preflight, all of it, before the ruling is claimed and before a port is opened
    try:
        ruling = check_ruling(args.ruling)
        if args.out.exists():
            raise bsn.SessionRefusal(f"{args.out} exists; evidence is never replaced")
        if shutil.which("sb") is None:
            raise bsn.SessionRefusal("`sb` (lrzsz) is not installed")
        table = load_frame_table()
        for far in (TARGET_FAR, *S2_FARS):
            validate_plan(pp.build_plan(far, pp.PINNED_DMA_ORDER, SENTINEL))
    except (bsn.SessionRefusal, ProbeStop, ValueError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    consumed = claim_ruling(args.ruling)          # atomic; one attempt per ruling
    args.out.mkdir(parents=True)

    outcome = "CRASHED before a summary was written"
    try:
        transport = bsn.SerialTransport(args.port)
        try:
            session = bsn.BoardSession(transport)
            summary = run_probe(session, args.out, ruling, table)
            outcome = summary["outcome"]
        finally:
            transport.close()
    except bsn.SessionRefusal as exc:
        outcome = f"REFUSED: {exc}"
    finally:
        record_outcome(consumed, outcome)
    if outcome != "PASS":
        print(outcome, file=sys.stderr)
        return 1
    print("PASS: S1, S2, S3 — records in", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
