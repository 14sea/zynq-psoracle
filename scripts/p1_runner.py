#!/usr/bin/env python3
"""P1 runner — baseline read → write A → read ×2 → write B → read ×2 → seal → terminal JTAG.

`docs/p1_spec.md` is the contract. Host-only until a ruling with the text
`whole-of-probe P1` exists; the ruling is claimed atomically before the port opens and is
consumed whatever happens. Reads are the S1–S3 plan and executor unchanged; writes are
`pcap_write_plan` plans re-validated against their canonical build before a byte is sent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import board_session as bsn  # noqa: E402
import pcap_probe_plan as pp  # noqa: E402
import pcap_probe_runner as pr  # noqa: E402
import pcap_write_plan as wp  # noqa: E402

TOOL_VERSION = "p1_runner.py/0.1.0"
RULING_TEXT = "whole-of-probe P1"

# pinned expectations (docs/p1_spec.md §2) — constants, checked against the builders at load
BASE_SHA256 = "0441772f66559a1c71f4559dc4405438fc9b8383ce1229139257a7fe6d7b8de9"
A_SHA256 = "8c78f1ce2829e7522dd08cddfe5b444990de3a94ee14ffd771dcb47635c70e3e"
B_SHA256 = "b6c91fb841c0df1240aee405c1cb1f6d9efad09b32c7378221bd702dc3408490"
PAD_SHA256 = BASE_SHA256          # the pad frame is blank in the base too
TARGET_FAR = wp.TARGET_FAR
PAD_FAR = wp.PAD_FAR

PRE_WRITE_CONTENT = "PRE_WRITE_CONTENT"
STAT_CRC_ERROR = 1 << 0            # UG470 v1.17 Table 5-29: STAT bit 0
JTAG_PROBE = REPO_ROOT / "scripts/probe_jtag_config_read.py"
JTAG_CFG = REPO_ROOT / "scripts/jtag_config_only.cfg"


def pinned_check(base: dict[int, list[int]]) -> None:
    """The constants above must be what the builders produce; otherwise refuse to start."""
    got = {"base": wp.pp_sha(base[TARGET_FAR]), "pad": wp.pp_sha(base[PAD_FAR]),
           "A": wp.build_write_plan("A", base)["frame_after_sha256"],
           "B": wp.build_write_plan("B", base)["frame_after_sha256"]}
    want = {"base": BASE_SHA256, "pad": PAD_SHA256, "A": A_SHA256, "B": B_SHA256}
    bad = {k for k in want if got[k] != want[k]}
    if bad:
        raise bsn.SessionRefusal(f"pinned P1 hashes disagree with the builders: {sorted(bad)}")


# ------------------------------------------------------------------ the write


def validate_write_plan(plan: dict, base: dict[int, list[int]]) -> None:
    canonical = wp.build_write_plan(plan["pattern"], base)
    if plan != canonical:
        diverging = sorted(k for k in set(plan) | set(canonical)
                           if plan.get(k) != canonical.get(k))
        raise ValueError(f"write plan differs from the canonical build in {diverging}")
    wp.check_write_plan(plan, base)


def execute_write_plan(capability, session: bsn.BoardSession, plan: dict,
                       base: dict[int, list[int]], stage_name: str) -> dict:
    if capability is not bsn.CONFIG_READ_CAPABILITY:
        raise bsn.SessionRefusal("execute_write_plan needs CONFIG_READ_CAPABILITY")
    validate_write_plan(plan, base)
    send = pr._Sender(session, plan)
    identity = session.authorise(capability)
    plmark = session.check_plmark()
    stage = {"tool": TOOL_VERSION, "stage": stage_name, "schema": "zynq-psmap/write_record/1",
             "identity": identity, "epoch": session.epoch, "plmark": plmark,
             "pattern": plan["pattern"], "pattern_value": f"{plan['pattern_value']:#06x}",
             "target_far": f"{plan['target_far']:#010x}", "pad_far": f"{plan['pad_far']:#010x}",
             "stream": [f"{w:#010x}" for w in plan["stream"]],
             "frame_after_sha256": plan["frame_after_sha256"],
             "dma_transaction": [f"{x:#010x}" for x in plan["dma_transaction"]],
             "observations": {}, "wait": None, "verdict": None, "stop": None, "detail": None,
             "started": time.time()}
    obs = stage["observations"]
    err_mask, clear_mask = plan["int_sts_error_mask"], plan["int_sts_clear_mask"]
    queued_at = None
    for step in plan["uboot_script"]:
        name, cmd = step["step"], step["cmd"]
        form, start, span = pp.parse_command(cmd)
        if form == "mw.l":
            send(cmd)
            if name == "dma-write" and start == pp.REG["DMA_DEST_LEN"]:
                queued_at = time.monotonic()
            continue
        if name == "ctrl-before":
            obs["ctrl_before"] = f"{send.words(cmd, start, 1)[0]:#010x}"
            if int(obs["ctrl_before"], 16) & pp.CTRL_MASK != pp.CTRL_REQUIRED:
                raise pr._stop(stage, pr.PRECONDITION,
                               f"CTRL {obs['ctrl_before']} fails the masked gate before the write")
        elif name == "ctrl-after":
            obs["ctrl_after"] = f"{send.words(cmd, start, 1)[0]:#010x}"
            if obs["ctrl_after"] != obs["ctrl_before"]:
                raise pr._stop(stage, pr.PRECONDITION,
                               f"CTRL changed across the write: {obs['ctrl_before']} -> "
                               f"{obs['ctrl_after']} (PCAP_RATE_EN or another bit moved)")
        elif name == "clear-verify-write":
            v = send.words(cmd, start, 1)[0]
            obs["int_sts_after_clear"] = f"{v:#010x}"
            if v & clear_mask:
                raise pr._stop(stage, pr.PRECONDITION,
                               f"INT_STS {v:#010x} did not clear ({v & clear_mask:#010x})")
        elif name == "wait-write":
            deadline = queued_at + plan["timeout_s"]
            polls = 0
            while True:
                v = send.words(cmd, start, 1)[0]
                polls += 1
                if v & err_mask:
                    stage["wait"] = {"int_sts": f"{v:#010x}", "polls": polls,
                                     "error_bits": pr.error_bit_names(v)}
                    if v & pr.INT_STS_RX_FIFO_OV:
                        raise pr._stop(stage, "OVERFLOW", f"write: RX_FIFO_OV ({v:#010x})")
                    raise pr._stop(stage, pr.DMA_ERROR,
                                   f"write: INT_STS {v:#010x} {pr.error_bit_names(v)}")
                if v & pp.INT_STS_D_P_DONE:
                    stage["wait"] = {"int_sts": f"{v:#010x}", "polls": polls,
                                     "elapsed_s": round(time.monotonic() - queued_at, 6),
                                     "elapsed_basis": "measured"}
                    break
                if time.monotonic() > deadline:
                    stage["wait"] = {"int_sts": f"{v:#010x}", "polls": polls}
                    raise pr._stop(stage, "TIMEOUT", f"write: no D_P_DONE in {plan['timeout_s']} s")
        else:
            raise bsn.SessionRefusal(f"the write plan has a read this runner does not gate: {name}")
    stage["verdict"] = "WRITTEN"
    stage["elapsed_s"] = round(time.time() - stage["started"], 3)
    return stage


# ------------------------------------------------------------------ reads with PRE_WRITE_CONTENT


def read_stage(session, table, expected: str, previous: str, name: str) -> dict:
    plan = pp.build_plan(TARGET_FAR, pp.PINNED_DMA_ORDER, pr.SENTINEL)
    try:
        rec = pr.execute_plan(bsn.CONFIG_READ_CAPABILITY, session, plan, table, expected, name)
    except pr.ProbeStop as stop:
        rec = stop.record
        if rec is not None and rec.get("verdict") in ("BLANK", "MISADDRESS",
                                                       "MISADDRESS_AMBIGUOUS", "NO_MATCH"):
            if rec.get("frame_sha256") == previous:
                rec["verdict_before_reclassification"] = rec["verdict"]
                rec["verdict"] = PRE_WRITE_CONTENT
                rec["detail"] = (f"the frame half equals the PREVIOUS pinned content "
                                 f"({previous[:16]}…); the write did not show in this read")
                raise pr.ProbeStop(PRE_WRITE_CONTENT, rec["detail"], rec) from None
        raise
    rec["previous_sha256"] = previous
    return rec


# ------------------------------------------------------------------ terminal JTAG


def run_jtag_terminal(out_dir: Path, fars=(TARGET_FAR, PAD_FAR)) -> dict:
    """The imported R4 probe as a subprocess. Terminal: nothing touches the board after it."""
    if shutil.which("openocd") is None:
        raise bsn.SessionRefusal("openocd is not installed; the terminal verifier cannot run")
    out = out_dir / "jtag.json"
    argv = [sys.executable, str(JTAG_PROBE), "--cfg", str(JTAG_CFG), "--out", str(out)]
    for far in fars:
        argv += ["--far", f"{far:#010x}"]
    done = subprocess.run(argv, capture_output=True, text=True, timeout=900, check=False)
    if not out.exists():
        raise bsn.SessionRefusal(f"the JTAG probe wrote no record: rc={done.returncode} "
                                 f"{done.stderr[-300:]}")
    return json.loads(out.read_text())


def jtag_verdict(record: dict) -> dict:
    if record.get("verdict") != "READ":
        return {"verdict": "HOLD", "detail": f"JTAG probe did not read: {record.get('stop_reason')}"}
    frames = record.get("frames", {})
    got_t = frames.get(f"{TARGET_FAR:#010x}", {}).get("frame_sha256")
    got_p = frames.get(f"{PAD_FAR:#010x}", {}).get("frame_sha256")
    ok_t, ok_p = got_t == B_SHA256, got_p == PAD_SHA256
    status = record.get("config_status")
    crc_error = None if status is None else bool(int(status, 16) & STAT_CRC_ERROR)
    ok_crc = crc_error is False           # unknown is not "no error"
    return {"verdict": "PASS" if (ok_t and ok_p and ok_crc) else "MISMATCH",
            "target_sha256": got_t, "target_matches_B": ok_t,
            "pad_sha256": got_p, "pad_matches_base": ok_p,
            "config_status": status, "crc_error": crc_error}


# ------------------------------------------------------------------ the chain


def run_p1(session: bsn.BoardSession, out_dir: Path, ruling: dict, table: dict | None = None,
           base: dict[int, list[int]] | None = None, jtag=run_jtag_terminal) -> dict:
    table = table or pr.load_frame_table()
    base = base or wp.base_frames()
    pinned_check(base)
    summary = {"tool": TOOL_VERSION, "ruling": ruling, "stages": {}, "outcome": None,
               "pinned": {"base": BASE_SHA256, "A": A_SHA256, "B": B_SHA256, "pad": PAD_SHA256}}

    def finish(rec: dict | None, name: str):
        if rec is not None:
            pr.write_record(out_dir, name, rec)
            summary["stages"][name] = rec.get("verdict")

    try:
        summary["precheck"] = pr.precheck(session)
        summary["identity"] = session.verify_identity()
        summary["setup_load"] = session.load_carrier(
            bsn.SETUP_LOAD_CAPABILITY, pr.CARRIER_BIT, pr.CARRIER_SHA256, out_dir / "ymodem.log")
        finish(read_stage(session, table, BASE_SHA256, BASE_SHA256, "P1_0_baseline"), "P1_0_baseline")
        finish(execute_write_plan(bsn.CONFIG_READ_CAPABILITY, session,
                                  wp.build_write_plan("A", base), base, "P1_1_write_A"), "P1_1_write_A")
        for i in range(2):
            finish(read_stage(session, table, A_SHA256, BASE_SHA256, f"P1_2_read_A_{i}"), f"P1_2_read_A_{i}")
        finish(execute_write_plan(bsn.CONFIG_READ_CAPABILITY, session,
                                  wp.build_write_plan("B", base), base, "P1_3_write_B"), "P1_3_write_B")
        for i in range(2):
            finish(read_stage(session, table, B_SHA256, A_SHA256, f"P1_4_read_B_{i}"), f"P1_4_read_B_{i}")
        # seal before the terminal verifier touches the die
        summary["sealed"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                             for p in sorted(out_dir.glob("P1_*.json"))}
        pr.write_record(out_dir, "sealed", summary["sealed"])
        summary["jtag"] = jtag_verdict(jtag(out_dir))
        summary["stages"]["P1_5_jtag"] = summary["jtag"]["verdict"]
        summary["outcome"] = "PASS" if summary["jtag"]["verdict"] == "PASS" else (
            "HOLD: terminal JTAG did not read" if summary["jtag"]["verdict"] == "HOLD"
            else f"STOP JTAG_MISMATCH: {summary['jtag']}")
    except pr.ProbeStop as stop:
        finish(stop.record, stop.record["stage"] if stop.record else "stop")
        summary["outcome"] = f"STOP {stop.verdict}: {stop.detail}"
    except bsn.SessionRefusal as refusal:
        summary["outcome"] = f"REFUSED: {refusal}"
    finally:
        summary["uart_log"] = session.log
        summary["disruptions"] = session.disruptions
        summary["transport_rereads"] = session.rereads
        summary["epoch_final"] = session.epoch
        pr.write_record(out_dir, "summary", summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ruling", type=Path, required=True, help="ruling text must be 'whole-of-probe P1'")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--port", default=bsn.PORT)
    args = ap.parse_args(argv)
    try:
        ruling = pr.check_ruling(args.ruling, text=RULING_TEXT)
        if args.out.exists():
            raise bsn.SessionRefusal(f"{args.out} exists; evidence is never replaced")
        for tool in ("sb", "openocd"):
            if shutil.which(tool) is None:
                raise bsn.SessionRefusal(f"`{tool}` is not installed")
        table = pr.load_frame_table()
        base = wp.base_frames()
        pinned_check(base)
        pr.validate_plan(pp.build_plan(TARGET_FAR, pp.PINNED_DMA_ORDER, pr.SENTINEL))
        for n in ("A", "B"):
            validate_write_plan(wp.build_write_plan(n, base), base)
    except (bsn.SessionRefusal, pr.ProbeStop, ValueError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    consumed = pr.claim_ruling(args.ruling)
    args.out.mkdir(parents=True)
    outcome = "CRASHED before a summary was written"
    try:
        transport = bsn.SerialTransport(args.port)
        try:
            session = bsn.BoardSession(transport)
            summary = run_p1(session, args.out, ruling, table, base)
            outcome = summary["outcome"]
        finally:
            transport.close()
    except bsn.SessionRefusal as exc:
        outcome = f"REFUSED: {exc}"
    finally:
        pr.record_outcome(consumed, outcome)
    if outcome != "PASS":
        print(outcome, file=sys.stderr)
        return 1
    print("PASS: P1 — records in", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
