#!/usr/bin/env python3
"""L2 = P2b runner — zynq-psmap's P2 protocol on the P3 carrier with two invariants
(`docs/l2_spec.md`): the eight stable-state words equal the baseline (P2, unchanged) AND
the heartbeat advances within its envelope, across a no-read control, ten pinned PCAP
reads, one envelope write and one readback. Ruling text: RULING_TEXT. No ruling exists.

Every line to the board is: a validated read plan's command, the L3 write path's commands
(stage + P1-shaped DMA), one of the nine pinned observe reads, one of the four FCLK reads,
or the session's named extras.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R / "scripts")); sys.path.insert(0, str(R / "host")); sys.path.insert(0, str(R))
import board_session as bsn  # noqa: E402
import p2_observe as ob  # noqa: E402
import pcap_probe_plan as pp  # noqa: E402
import pcap_probe_runner as pr  # noqa: E402
import l2_heartbeat as hb  # noqa: E402
import l3_runner as l3  # noqa: E402
import p3_gate as g  # noqa: E402
import p3_oracle as po  # noqa: E402
import json  # noqa: E402
from validators import records  # noqa: E402

TOOL_VERSION = "l2_runner.py/0.1.0"
RULING_TEXT = "whole-of-probe P3-L2"
N_READS = 10
T_CONTROL_DERIVED_S = 30.0
HEARTBEAT_ADDR = po.axi(po.HEARTBEAT)
OBSERVE_COMMANDS = tuple(ob.OBSERVE_COMMANDS) + (f"md.l {HEARTBEAT_ADDR:#010x} 1",)


class _Observer:
    def __init__(self, session: bsn.BoardSession, clock):
        self.session, self.clock = session, clock
        self.allowed = set(OBSERVE_COMMANDS) | set(ob.FCLK_COMMANDS)

    def word(self, cmd: str, addr: int) -> int:
        if cmd not in self.allowed:
            raise bsn.SessionRefusal(f"not a pinned observe/fclk read: {cmd!r}")
        return self.session.read_command(cmd, addr, 1)[0]

    def sample(self) -> tuple[dict[int, int], float, int]:
        words = {a: self.word(f"md.l {a:#010x} 1", a) for a in ob.OBSERVABLE}
        h = self.word(f"md.l {HEARTBEAT_ADDR:#010x} 1", HEARTBEAT_ADDR)
        return words, self.clock(), h        # the heartbeat's host time is taken at its reply

    def fclk0(self) -> dict:
        vals = [self.word(f"md.l {a:#010x} 1", a)
                for a in (ob.IO_PLL_CTRL, ob.ARM_PLL_CTRL, ob.DDR_PLL_CTRL, ob.FPGA0_CLK_CTRL)]
        return ob.fclk0_mhz(*vals)


def _fmt(s):
    return {f"{a:#010x}": f"{v:#010x}" for a, v in s.items()}


def run_l2(session: bsn.BoardSession, out_dir: Path, ruling: dict, cfg: dict,
           sleep=time.sleep, clock=time.monotonic) -> dict:
    manifest = cfg["manifest"]
    table = cfg.get("table") or l3.load_p3_table(cfg["bitstream"], manifest)
    phen = g.load_manifest()
    summary = {"tool": TOOL_VERSION, "ruling": ruling, "stages": {}, "samples": [], "outcome": None,
               "observable": [f"{a:#010x}" for a in ob.OBSERVABLE] + [f"{HEARTBEAT_ADDR:#010x}"],
               "bitstream_sha256": table["sha256"]}
    obs = _Observer(session, clock)
    state_samples: list[tuple[str, dict[int, int]]] = []
    hb_samples: list[tuple[str, float, int]] = []

    def take(name: str):
        session.check_plmark()
        words, t, h = obs.sample()
        state_samples.append((name, words)); hb_samples.append((name, t, h))
        summary["samples"].append({"step": name, "words": _fmt(words), "heartbeat": f"{h:#010x}", "t_host": t})
        lp = ob.liveness_problems(words)
        if lp:
            raise pr.ProbeStop("AXI_NOT_ALIVE", f"{name}: " + "; ".join(lp))
        return words

    def finish(rec, name):
        if rec is not None:
            pr.write_record(out_dir, name, rec); summary["stages"][name] = rec.get("verdict")

    try:
        summary["precheck"] = pr.precheck(session)
        summary["identity"] = session.verify_identity()
        summary["setup_load"] = session.load_carrier(bsn.SETUP_LOAD_CAPABILITY, cfg["bitstream"],
                                                     manifest["bitstream_sha256"], out_dir / "ymodem.log")
        session.authorise(bsn.CONFIG_READ_CAPABILITY)
        f = obs.fclk0(); summary["fclk0"] = f
        finish({"stage": "L2_0_fclk", "verdict": "OK" if f["ok"] else "PRECONDITION", **f}, "L2_0_fclk")
        if not f["ok"]:
            raise pr.ProbeStop(pr.PRECONDITION, f"FCLK0 decodes to {f['mhz']} MHz, not 50 ± 0.5")
        fhz = f["mhz"] * 1e6
        baseline = take("L2_1_baseline")
        finish({"stage": "L2_1_baseline", "verdict": "OK", "words": _fmt(baseline)}, "L2_1_baseline")
        sleep(T_CONTROL_DERIVED_S)
        ctrl = take("L2_2_control")
        d = ob.compare(baseline, ctrl)
        hv = hb.interval_verdict(fhz, hb_samples[0][1], hb_samples[0][2], hb_samples[1][1], hb_samples[1][2])
        finish({"stage": "L2_2_control", "verdict": "OK" if not d and hv["ok"] else "CONTROL_UNSTABLE",
                "wait_s": T_CONTROL_DERIVED_S, "diff": d, "heartbeat": hv}, "L2_2_control")
        if d or not hv["ok"]:
            summary["outcome"] = "HOLD CONTROL_UNSTABLE: " + ("state drifted" if d else "heartbeat outside its envelope") + " with no PCAP activity"
            return summary
        positive_control = int(manifest["positive_control"]["far"], 16)
        t0 = clock()
        for i in range(N_READS):
            plan = pp.build_plan(positive_control, pp.PINNED_DMA_ORDER, pr.SENTINEL)
            rec = pr.execute_plan(bsn.CONFIG_READ_CAPABILITY, session, plan, table,
                                  pr.frame_sha256(table["frames"][positive_control]), f"L2_3_read_{i}")
            s = take(f"L2_3_read_{i}")
            rec["observable_diff"] = ob.compare(baseline, s); finish(rec, f"L2_3_read_{i}")
        sleep(max(0.5, clock() - t0))
        post = take("L2_4_post")
        finish({"stage": "L2_4_post", "verdict": "OK", "diff": ob.compare(baseline, post)}, "L2_4_post")
        # one envelope write: the known answer's envelope 0 (gate-passed at link 1)
        cand = g.known_answer_candidate(phen)
        streams = g.build_streams(cand, phen)
        if not g.gate(streams, phen)["writable"]:
            raise pr.ProbeStop(pr.PRECONDITION, "the known answer is not writable")
        far_sets = {e["far_set"] for e in g.envelopes(phen)}
        l3.stage_and_reread(session, streams[0]["words"], far_sets)
        wrec = l3.execute_write(session, "L2_5_write")
        s = take("L2_5_write"); wrec["observable_diff"] = ob.compare(baseline, s); finish(wrec, "L2_5_write")
        rec = l3.readback_frame(session, table, 0x00400A20, cand[0x00400A20], "L2_6_readback")
        s = take("L2_6_readback"); rec["observable_diff"] = ob.compare(baseline, s); finish(rec, "L2_6_readback")
        # p2_observe (imported, unchanged) names the control "P2_2_control"; L2's step is L2_2_control
        state = ob.adjudicate(baseline, [("P2_2_control", state_samples[1][1])] + state_samples[2:])
        beat = hb.adjudicate(fhz, hb_samples)
        summary["continuity"] = {"state": state, "heartbeat": beat}
        if state["verdict"] == "PASS" and beat["verdict"] == "PASS":
            summary["outcome"] = "PASS"
            summary["measured_envelope"] = {"ticks_per_s_min": min(v["ticks"] / v["dt_s"] for v in beat["intervals"]),
                                            "ticks_per_s_max": max(v["ticks"] / v["dt_s"] for v in beat["intervals"])}
        else:
            bad = state if state["verdict"] != "PASS" else beat
            summary["outcome"] = f"STOP {bad['verdict']} at {bad.get('at')}: {bad.get('detail', bad.get('problems'))}"
    except (pr.ProbeStop, l3.Stop) as stop:
        rec = getattr(stop, "record", None)
        finish(rec, rec["stage"] if rec and "stage" in rec else "stop")
        summary["outcome"] = f"STOP {stop.verdict}: {stop.detail}"
    except bsn.SessionRefusal as refusal:
        summary["outcome"] = f"REFUSED: {refusal}"
    finally:
        summary["uart_log"] = session.log; summary["disruptions"] = session.disruptions
        summary["transport_rereads"] = session.rereads; summary["epoch_final"] = session.epoch
        pr.write_record(out_dir, "summary", summary)
    return summary


def _install_sigterm():
    """A SIGTERM (a shell timeout, a killed terminal) must still write the summary and the
    ruling outcome: it becomes a SessionRefusal inside the chain (L2 run #1, 2026-08-29)."""
    import signal

    def _h(signum, frame):
        raise bsn.SessionRefusal(f"signal {signum} received by the runner (host-side kill)")
    signal.signal(signal.SIGTERM, _h); signal.signal(signal.SIGHUP, _h)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ruling", type=Path, required=True); ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, required=True); ap.add_argument("--bitstream", type=Path, required=True)
    ap.add_argument("--port", default=bsn.PORT)
    a = ap.parse_args(argv)
    try:
        ruling = pr.check_ruling(a.ruling, text=RULING_TEXT)
        if a.out.exists():
            raise bsn.SessionRefusal(f"{a.out} exists; evidence is never replaced")
        if shutil.which("sb") is None:
            raise bsn.SessionRefusal("`sb` is not installed")
        manifest = json.loads(a.manifest.read_text()); records.validate(manifest)
        cfg = {"manifest": manifest, "bitstream": a.bitstream, "table": l3.load_p3_table(a.bitstream, manifest)}
        pr.validate_plan(pp.build_plan(int(manifest["positive_control"]["far"], 16), pp.PINNED_DMA_ORDER, pr.SENTINEL))
    except (bsn.SessionRefusal, pr.ProbeStop, ValueError, records.RecordError, OSError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr); return 2
    consumed = pr.claim_ruling(a.ruling); a.out.mkdir(parents=True)
    _install_sigterm()
    outcome = "CRASHED before a summary was written"
    try:
        transport = bsn.SerialTransport(a.port)
        try:
            outcome = run_l2(bsn.BoardSession(transport), a.out, ruling, cfg)["outcome"]
        finally:
            transport.close()
    except bsn.SessionRefusal as exc:
        outcome = f"REFUSED: {exc}"
    finally:
        pr.record_outcome(consumed, outcome)
    print(outcome, file=sys.stderr if outcome != "PASS" else sys.stdout)
    return 0 if outcome == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
