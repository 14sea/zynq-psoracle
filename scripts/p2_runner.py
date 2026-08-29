#!/usr/bin/env python3
"""P2 runner — FCLK0 → baseline O₀ → no-read control → 10 reads (O after each) → post →
one write A (O after) → readback (O after). `docs/p2_spec.md` is the contract.

Host-only until a ruling with the text `whole-of-probe P2` exists. Every line sent to the
board is either a command of a validated plan (read: `pcap_probe_plan`; write:
`pcap_write_plan`), one of the eight pinned AXI observe reads, one of the four pinned
FCLK register reads, or the runner's named extras — nothing else reaches the transport.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import board_session as bsn  # noqa: E402
import p1_runner as p1  # noqa: E402
import p2_observe as ob  # noqa: E402
import pcap_probe_plan as pp  # noqa: E402
import pcap_probe_runner as pr  # noqa: E402
import pcap_write_plan as wp  # noqa: E402

TOOL_VERSION = "p2_runner.py/0.1.0"
RULING_TEXT = "whole-of-probe P2"
READ_FAR = 0x00000B99                 # the live-logic INT frame S1–S3 read
READ_EXPECTED = pr.TARGET_SHA256
N_READS = 10
T_CONTROL_DERIVED_S = 30.0            # pre-run estimate for the first control wait (derived)


class _Observer:
    """The only path to the eight AXI words and the four FCLK words; refuses anything else."""

    def __init__(self, session: bsn.BoardSession):
        self.session = session
        self.allowed = set(ob.OBSERVE_COMMANDS) | set(ob.FCLK_COMMANDS)

    def word(self, cmd: str, addr: int) -> int:
        if cmd not in self.allowed:
            raise bsn.SessionRefusal(f"not a pinned observe/fclk read: {cmd!r}")
        return self.session.read_command(cmd, addr, 1)[0]      # md.l only; re-read policy §2b

    def sample(self) -> dict[int, int]:
        return {a: self.word(f"md.l {a:#010x} 1", a) for a in ob.OBSERVABLE}

    def fclk0(self) -> dict:
        vals = [self.word(f"md.l {a:#010x} 1", a)
                for a in (ob.IO_PLL_CTRL, ob.ARM_PLL_CTRL, ob.DDR_PLL_CTRL, ob.FPGA0_CLK_CTRL)]
        return ob.fclk0_mhz(*vals)


def _fmt(sample: dict[int, int]) -> dict:
    return {f"{a:#010x}": f"{v:#010x}" for a, v in sample.items()}


def run_p2(session: bsn.BoardSession, out_dir: Path, ruling: dict, table: dict | None = None,
           base: dict[int, list[int]] | None = None, sleep=time.sleep) -> dict:
    table = table or pr.load_frame_table()
    base = base or wp.base_frames()
    p1.pinned_check(base)
    summary = {"tool": TOOL_VERSION, "ruling": ruling, "stages": {}, "samples": [],
               "outcome": None, "observable": [f"{a:#010x}" for a in ob.OBSERVABLE]}
    obs = _Observer(session)
    samples: list[tuple[str, dict[int, int]]] = []

    def take(name: str) -> dict[int, int]:
        session.check_plmark()
        s = obs.sample()
        samples.append((name, s))
        summary["samples"].append({"step": name, "words": _fmt(s), "at": time.time()})
        lp = ob.liveness_problems(s)
        if lp:
            raise pr.ProbeStop("AXI_NOT_ALIVE", f"{name}: " + "; ".join(lp))
        return s

    def finish(rec: dict | None, name: str):
        if rec is not None:
            pr.write_record(out_dir, name, rec)
            summary["stages"][name] = rec.get("verdict")

    try:
        summary["precheck"] = pr.precheck(session)
        summary["identity"] = session.verify_identity()
        summary["setup_load"] = session.load_carrier(
            bsn.SETUP_LOAD_CAPABILITY, pr.CARRIER_BIT, pr.CARRIER_SHA256, out_dir / "ymodem.log")
        session.authorise(bsn.CONFIG_READ_CAPABILITY)
        # 1 — FCLK0, read-only decode
        f = obs.fclk0()
        summary["fclk0"] = f
        finish({"stage": "P2_0_fclk", "verdict": "OK" if f["ok"] else "PRECONDITION", **f}, "P2_0_fclk")
        if not f["ok"]:
            raise pr.ProbeStop(pr.PRECONDITION, f"FCLK0 decodes to {f['mhz']} MHz, not 50 ± 0.5")
        # 2 — baseline
        baseline = take("P2_1_baseline")
        summary["baseline"] = _fmt(baseline)
        finish({"stage": "P2_1_baseline", "verdict": "OK", "words": _fmt(baseline)}, "P2_1_baseline")
        # 3 — no-read control
        sleep(T_CONTROL_DERIVED_S)
        ctrl = take("P2_2_control")
        d = ob.compare(baseline, ctrl)
        finish({"stage": "P2_2_control", "verdict": "OK" if not d else "CONTROL_UNSTABLE",
                "wait_s": T_CONTROL_DERIVED_S, "wait_basis": "derived", "diff": d}, "P2_2_control")
        if d:
            summary["outcome"] = "HOLD CONTROL_UNSTABLE: the observable drifted with no PCAP activity"
            return summary
        # 4 — ten reads, O after each
        t0 = time.monotonic()
        for i in range(N_READS):
            plan = pp.build_plan(READ_FAR, pp.PINNED_DMA_ORDER, pr.SENTINEL)
            rec = pr.execute_plan(bsn.CONFIG_READ_CAPABILITY, session, plan, table, READ_EXPECTED,
                                  f"P2_3_read_{i}")
            s = take(f"P2_3_read_{i}")
            rec["observable_after"] = _fmt(s)
            rec["observable_diff"] = ob.compare(baseline, s)
            finish(rec, f"P2_3_read_{i}")
        t_reads = time.monotonic() - t0
        # 5 — post wait, measured span
        sleep(t_reads)
        post = take("P2_4_post")
        finish({"stage": "P2_4_post", "verdict": "OK", "wait_s": round(t_reads, 3),
                "wait_basis": "measured", "diff": ob.compare(baseline, post)}, "P2_4_post")
        # 6 — one write A, O after
        wrec = p1.execute_write_plan(bsn.CONFIG_READ_CAPABILITY, session,
                                     wp.build_write_plan("A", base), base, "P2_5_write")
        s = take("P2_5_write")
        wrec["observable_after"] = _fmt(s)
        wrec["observable_diff"] = ob.compare(baseline, s)
        finish(wrec, "P2_5_write")
        # 7 — readback of the written frame, O after
        rec = p1.read_stage(session, table, p1.A_SHA256, p1.BASE_SHA256, "P2_6_readback")
        s = take("P2_6_readback")
        rec["observable_after"] = _fmt(s)
        rec["observable_diff"] = ob.compare(baseline, s)
        finish(rec, "P2_6_readback")
        # adjudicate the whole series
        verdict = ob.adjudicate(baseline, samples[1:])     # samples[0] is the baseline itself
        summary["continuity"] = verdict
        summary["outcome"] = "PASS" if verdict["verdict"] == "PASS" else (
            f"STOP {verdict['verdict']} at {verdict.get('at')}: {verdict.get('detail', verdict.get('problems'))}")
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
    ap.add_argument("--ruling", type=Path, required=True, help="ruling text must be 'whole-of-probe P2'")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--port", default=bsn.PORT)
    args = ap.parse_args(argv)
    try:
        ruling = pr.check_ruling(args.ruling, text=RULING_TEXT)
        if args.out.exists():
            raise bsn.SessionRefusal(f"{args.out} exists; evidence is never replaced")
        if shutil.which("sb") is None:
            raise bsn.SessionRefusal("`sb` is not installed")
        table = pr.load_frame_table()
        base = wp.base_frames()
        p1.pinned_check(base)
        pr.validate_plan(pp.build_plan(READ_FAR, pp.PINNED_DMA_ORDER, pr.SENTINEL))
        pr.validate_plan(pp.build_plan(p1.TARGET_FAR, pp.PINNED_DMA_ORDER, pr.SENTINEL))
        p1.validate_write_plan(wp.build_write_plan("A", base), base)
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
            summary = run_p2(session, args.out, ruling, table, base)
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
    print("PASS: P2 — records in", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
