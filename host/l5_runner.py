#!/usr/bin/env python3
"""L5 — the standalone loop on the board. Ruling text RULING_TEXT.

The rung the line was missing an executable for: L2/L3/L4 each had a runner, L5 had only
libraries. What this drives is deliberately small, because on this rung the LOOP LIVES IN
THE FIRMWARE (D1): the host is the notary, not the decision maker.

    1. claim the ruling; refuse without a principal-boundary record < 6 h old
    2. U-Boot: precheck, identity, dcache off
    3. BLOCKING PREFLIGHT: read CPU_CLK_CTRL (0xF8000120) once and store it — until this
       read exists, CPU_6x4x and PERIPHCLK are assumptions (docs/l5_prereg.md §4)
    4. setup-load the carrier bitstream; ask the signer to provision K over JTAG (P3-K)
    5. write the identity page to DDR, ymodem the application image to 0x0200_0000, `go`
    6. from `go` on, the console belongs to the application: every line is fed to the real
       Collector, SIGNREQ lines are answered by the real NotaryRelay + signer, and (when
       --audit-all) an AUDITREQ is attached to every exchange BEFORE the reply
    7. on the epoch end, assemble the run log and adjudicate it with the real
       validate_standalone_run_log; seal the evidence either way

The host never proposes a candidate, never scores and never arms: it relays, witnesses and
records. A CRASHED end is not repaired -- the collector writes the summary, the runner
stops without restoring, and the evidence is sealed as it stands (prereg §4).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import sys
import time
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R / "scripts")); sys.path.insert(0, str(R / "host")); sys.path.insert(0, str(R))
sys.path.insert(0, str(R / "imported/fabricmap/scripts"))
import board_session as bsn  # noqa: E402
import p2_observe as ob  # noqa: E402
import pcap_probe_runner as pr  # noqa: E402
import l3_runner as l3  # noqa: E402
import l5_notary as n  # noqa: E402
import l5_refloop as rf  # noqa: E402
import p3_gate as g  # noqa: E402
import p3_genome as gn  # noqa: E402
import p3_oracle as po  # noqa: E402
from validators import records  # noqa: E402

TOOL_VERSION = "l5_runner.py/0.1.0"
RULING_TEXT = "whole-of-probe P3-L5"
CPU_CLK_CTRL = 0xF8000120          # the blocking preflight, prereg §4
APP_LOAD_ADDR = 0x02000000
PAGE_ADDR = 0x10440000
UBOOT_PROMPT = re.compile(rb"(zynq-uboot>|U-Boot \d)")


class LineReader:
    """Splits the console byte stream into lines without ever discarding anything: the
    bytes are also kept verbatim for the evidence, and a U-Boot banner is a CRASH signal
    rather than noise to be skipped."""

    def __init__(self, transport):
        self.transport = transport
        self.buf = b""
        self.raw = bytearray()

    def poll(self) -> list[str]:
        chunk = self.transport.drain()
        if not chunk:
            return []
        self.raw += chunk
        self.buf += chunk
        out = []
        while b"\n" in self.buf:
            line, self.buf = self.buf.split(b"\n", 1)
            out.append(line.decode("ascii", "replace").rstrip("\r"))
        return out

    def saw_uboot_banner(self) -> bool:
        return bool(UBOOT_PROMPT.search(self.raw[-4096:]))


def send_raw_line(transport, line: str) -> None:
    """The application terminates a line on '\\n' and skips '\\r' (p3_app.c recv_line), so
    the reply must end in '\\n'. board_session.send_line appends '\\r' and is imported from
    zynq-psmap, which must not be modified, hence the direct write here."""
    data = line if line.endswith("\n") else line + "\n"
    transport._serial.write(data.encode("ascii"))  # noqa: SLF001 — see docstring


def classify_rejection(exc: records.RecordError) -> str:
    """A validator rejection, classified the way `docs/l5_prereg.md` §5 classifies it. Only a
    `Falsified` rejection — one of §3's items, raised as that type by the validator — is a
    KILL. Every other RecordError is a schema, accounting or instrument defect: a HOLD.

    Session 3 (2026-09-01) ended with the runner printing `KILL run_log rejected: audit must
    report audited <= total (rule ix)` for a counter the firmware got wrong; the owner ruled
    the session HOLD and this mapping wrong. The evidence keeps the literal string it was
    given; the mapping is fixed here, named, and tested in both directions."""
    if isinstance(exc, records.Falsified):
        return f"KILL falsified: {exc}"
    return f"HOLD instrument: run_log rejected: {exc}"


def outcome_for(epoch_end: dict) -> str:
    """The session verdict. Only a COMPLETED epoch can be a PASS — a STOPPED one (including
    the STOP_ARM case session 1 hit), a PROTOCOL one and a CRASHED one are all HOLDs. Named
    and tested rather than inlined, so "does a non-consumed ARM report PASS?" is answered by
    a test instead of by reading the expression."""
    kind = epoch_end["kind"]
    if kind == "COMPLETED":
        return "PASS"
    return f"HOLD {kind}: {epoch_end.get('reason')}"


def build_page(token: str, uboot_epoch: int, image_sha: str, carrier_sha: str, nonce: int,
               status: int, seed: int, budget: int, flags: int, fclk0_hz: int) -> list[int]:
    return rf.build_identity_page(token, uboot_epoch, int(image_sha[-8:], 16), carrier_sha,
                                  nonce, status, seed, budget, flags, fclk0_hz)


def run_l5(session: bsn.BoardSession, out_dir: Path, ruling: dict, cfg: dict) -> dict:
    manifest = cfg["manifest"]
    phen = g.load_manifest()
    token = cfg["token"]
    summary = {"tool": TOOL_VERSION, "ruling": ruling, "outcome": None,
               "token": token, "stages": {}}
    collector = n.Collector(token, heartbeat_s=cfg["heartbeat_s"])
    relay = n.NotaryRelay(token, cfg["signer"].sign_genome, drop_budget=cfg["drop_budget"])
    reader = None

    def finish(rec, name):
        pr.write_record(out_dir, name, rec)
        summary["stages"][name] = rec.get("verdict", "recorded")

    try:
        summary["precheck"] = pr.precheck(session)
        summary["identity"] = session.verify_identity()
        l3.ensure_dcache_off(session)

        # ---- 3. the blocking preflight: one read, stored, before anything else -------
        cpu_clk = session.read_word(CPU_CLK_CTRL)
        preflight = {"stage": "L5_0_preflight", "CPU_CLK_CTRL": f"{cpu_clk:#010x}",
                     "addr": f"{CPU_CLK_CTRL:#010x}",
                     "note": "prereg §4: until this read exists CPU_6x4x and PERIPHCLK are "
                             "assumed 6:2:1; it is recorded here as observed fact",
                     "verdict": "READ"}
        finish(preflight, "L5_0_preflight")
        summary["cpu_clk_ctrl"] = preflight["CPU_CLK_CTRL"]

        fclk = ob.fclk0_mhz(*[session.read_word(a) for a in
                              (ob.IO_PLL_CTRL, ob.ARM_PLL_CTRL, ob.DDR_PLL_CTRL,
                               ob.FPGA0_CLK_CTRL)])
        summary["fclk0"] = fclk

        # ---- 4. carrier + key --------------------------------------------------------
        summary["setup_load"] = session.load_carrier(
            bsn.SETUP_LOAD_CAPABILITY, cfg["bitstream"], manifest["bitstream_sha256"],
            out_dir / "ymodem.log")
        summary["provisioning"] = cfg["signer"].provision(
            execute=cfg["provision_execute"], ruling=cfg["provision_ruling"])
        plane = l3.Plane(session)
        status = plane.read(po.STATUS)
        if not status >> po.ST["key_loaded"] & 1:
            raise l3.Stop("KEY_NOT_LOADED", f"STATUS {status:#010x}")
        nonce = plane.read(po.NONCE_LO) | plane.read(po.NONCE_HI) << 32

        # ---- 5. identity page, image, go ---------------------------------------------
        page = build_page(token, session.epoch, cfg["image_sha256"],
                          manifest["bitstream_sha256"], nonce, status, cfg["seed"],
                          cfg["budget"], cfg["flags"], int(fclk["mhz"] * 1e6))
        for i, w in enumerate(page):
            session.command(f"mw.l {PAGE_ADDR + 4 * i:#010x} {w:#010x} 1")
        readback = session.read_words(PAGE_ADDR, len(page))
        if readback != page:
            raise l3.Stop("PAGE_MISMATCH", "the identity page did not read back as written")
        finish({"stage": "L5_1_identity_page", "words": [f"{w:#010x}" for w in page],
                "verdict": "WRITTEN"}, "L5_1_identity_page")

        session.begin_ymodem(APP_LOAD_ADDR)
        session.finish_ymodem(cfg["image"], out_dir / "ymodem_app.log",
                              cfg["image"].stat().st_size)
        summary["image_loaded"] = {"addr": f"{APP_LOAD_ADDR:#010x}",
                                   "sha256": cfg["image_sha256"],
                                   "bytes": cfg["image"].stat().st_size}

        # ---- 6. hand the console to the application ----------------------------------
        reader = LineReader(session.transport)
        send_raw_line(session.transport, f"go {APP_LOAD_ADDR:#x}")
        deadline = time.time() + cfg["session_timeout_s"]
        audit_sent_for = set()
        while collector.epoch_end is None and time.time() < deadline:
            for line in reader.poll():
                if not line.startswith(n.MAGIC):
                    continue                     # console noise is not evidence of a frame
                collector.on_line(line)
                try:
                    f = n.parse_line(line)
                except (n.FrameError, n.CrcError):
                    continue
                if f["type"] != n.T_SIGNREQ:
                    continue
                if cfg["audit_all"] and f["seq"] not in audit_sent_for:
                    # attached BEFORE the reply: the application serves the raw words after
                    # link 3 and before the record that claims them (spec §4.7)
                    audit_sent_for.add(f["seq"])
                    send_raw_line(session.transport,
                                  n.build_line(n.T_AUDITREQ, f["seq"], token,
                                               n.encode_payload({"seq": f["seq"]})))
                reply = relay.handle_line(line)
                if reply is not None:
                    send_raw_line(session.transport, reply)
            if reader.saw_uboot_banner():
                collector.on_banner()
            collector.poll()
            time.sleep(0.02)
        if collector.epoch_end is None:
            collector._crash(f"the runner's own {cfg['session_timeout_s']} s bound elapsed")

        # ---- 7. assemble and adjudicate ----------------------------------------------
        (out_dir / "console.log").write_bytes(bytes(reader.raw))
        summary["epoch_end"] = collector.epoch_end
        summary["audits"] = len(collector.audits)
        if collector.session_summary is None:
            collector.session_summary = collector.crashed_summary(
                crc_dropped=relay.crc_dropped, drop_budget=cfg["drop_budget"])
        log = {"control_plane": "standalone", "app_identity": collector.app_identity,
               "loop_records": collector.loop_records,
               "session_summary": collector.session_summary,
               "notary_log": relay.notary_log()}
        if collector.closing_negative is not None:
            log["closing_negative"] = collector.closing_negative
        pr.write_record(out_dir, "run_log", log)
        pr.write_record(out_dir, "audits", {"chunks": collector.audits})
        blank_commit = g.gate(g.build_streams(
            gn.frames_from_genome(gn.blank_genome(phen), phen), phen), phen)["candidate_sha256"]
        try:
            summary["run_log_validation"] = records.validate_standalone_run_log(
                log, blank_commit, cfg["seed_nonce"])
            if cfg["audit_all"]:
                # the session-1 audit condition, checked rather than asserted in prose
                summary["audit_policy"] = records.check_audit_policy(log)
            summary["outcome"] = outcome_for(collector.epoch_end)
        except records.RecordError as exc:
            summary["run_log_validation"] = f"REJECTED: {exc}"
            summary["outcome"] = classify_rejection(exc)
    except l3.Stop as stop:
        summary["outcome"] = (f"KILL {stop.detail}" if stop.verdict == "KILL"
                              else f"STOP {stop.verdict}: {stop.detail}")
    except pr.ProbeStop as stop:
        summary["outcome"] = f"STOP {stop.verdict}: {stop.detail}"
    except bsn.SessionRefusal as refusal:
        summary["outcome"] = f"REFUSED: {refusal}"
    except Exception as exc:  # noqa: BLE001 — any exception must still leave a summary
        import traceback
        summary["outcome"] = f"CRASHED host-side: {type(exc).__name__}: {exc}"
        summary["traceback"] = traceback.format_exc()
    finally:
        if reader is not None and not (out_dir / "console.log").exists():
            (out_dir / "console.log").write_bytes(bytes(reader.raw))
        summary["uart_log"] = session.log
        summary["disruptions"] = session.disruptions
        summary["transport_rereads"] = session.rereads
        summary["epoch_final"] = session.epoch
        summary["crc_dropped"] = relay.crc_dropped
        pr.write_record(out_dir, "summary", summary)
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ruling", type=Path, required=True)
    ap.add_argument("--provision-ruling", type=Path, default=None)
    ap.add_argument("--boundary", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, required=True, help="the carrier manifest")
    ap.add_argument("--l5-manifest", type=Path, default=R / "manifests/l5_manifest.json")
    ap.add_argument("--bitstream", type=Path, required=True)
    ap.add_argument("--image", type=Path, default=R / "firmware/bsp/out/p3_app.bin")
    ap.add_argument("--key", type=Path, default=Path("/var/lib/p3signer/keys/K.bin"))
    ap.add_argument("--signer-user", default="p3signer")
    ap.add_argument("--port", default=bsn.PORT)
    ap.add_argument("--budget", type=int, default=8, help="N candidates (prereg: 8)")
    ap.add_argument("--audit-all", action="store_true",
                    help="prereg: the first session audits every candidate")
    ap.add_argument("--session-timeout-s", type=float, default=7200.0)
    a = ap.parse_args(argv)
    try:
        ruling = pr.check_ruling(a.ruling, text=RULING_TEXT)
        if a.out.exists():
            raise bsn.SessionRefusal(f"{a.out} exists; evidence is never replaced")
        if shutil.which("sb") is None:
            raise bsn.SessionRefusal("`sb` is not installed")
        if not a.image.is_file():
            raise bsn.SessionRefusal(f"no application image at {a.image}")
        manifest = json.loads(a.manifest.read_text()); records.validate(manifest)
        l5m = json.loads(a.l5_manifest.read_text())
        boundary = json.loads(a.boundary.read_text())
        records.boundary_established(boundary, time.time())
        image_sha = hashlib.sha256(a.image.read_bytes()).hexdigest()
        pinned = l5m["pinned_at_build"]["app_image_sha256"]
        if image_sha != pinned:
            raise bsn.SessionRefusal(
                f"the image is not the pinned one: {image_sha[:16]}… != {pinned[:16]}…")
        if l5m["pinned_at_build"]["watchdog_enabled"]:
            raise bsn.SessionRefusal("this runner only runs the watchdog-off session (D-c)")
        seed = l5m["carrier"]["nonce_seed"]
        cfg = {"manifest": manifest, "bitstream": a.bitstream, "image": a.image,
               "image_sha256": image_sha, "consts": po.load_constants(),
               "signer": l3.SubprocessSigner(a.key, signer_user=a.signer_user),
               "provision_execute": a.provision_ruling is not None,
               "provision_ruling": a.provision_ruling,
               "token": secrets.token_hex(16), "seed": l5m["genome"].get("search_seed", 1),
               "seed_nonce": int(seed, 16), "budget": a.budget,
               "flags": 0,  # bit0 holdout off, bit1 watchdog off (D-c option 2)
               "audit_all": a.audit_all,
               "heartbeat_s": l5m["protocol"]["heartbeat_s"],
               "drop_budget": l5m["protocol"]["crc_drop_budget_per_session"],
               "session_timeout_s": a.session_timeout_s}
    except (bsn.SessionRefusal, pr.ProbeStop, ValueError, records.RecordError, OSError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    consumed = pr.claim_ruling(a.ruling)
    a.out.mkdir(parents=True)
    l3._install_sigterm()
    outcome = "CRASHED before a summary was written"
    try:
        transport = bsn.SerialTransport(a.port)
        try:
            outcome = run_l5(bsn.BoardSession(transport), a.out, ruling, cfg)["outcome"]
        finally:
            transport.close()
    except bsn.SessionRefusal as exc:
        outcome = f"REFUSED: {exc}"
    finally:
        pr.record_outcome(consumed, outcome)
        if a.provision_ruling:
            l3._record_pk(a.provision_ruling, outcome)
    print(outcome, file=sys.stderr if outcome != "PASS" else sys.stdout)
    return 0 if outcome == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
