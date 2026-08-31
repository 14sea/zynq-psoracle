#!/usr/bin/env python3
"""L4 — fault, restore, baseline (`docs/p3_architecture.md` §6 L4). Ruling text RULING_TEXT.

    gate_refused (host-only, no ruling, no board): an illegal candidate is refused by link 1
        and never sent — the record is the gate verdict itself.
    on-board session (own ruling + a `provisioning P3-K` ruling):
      1. stage envelope 0 of the known answer, then DELIBERATELY corrupt one staged word
         (a `mw.l` to WR_BUF) → link 2 re-read must STOP → prove NO DMA happened
         (INT_STS cleared before, D_P_DONE still clear after)
      2. restore: stage + write all three envelopes of the BLANK candidate (= the pinned base),
         link 2 on each, then link 3 readback of all twelve target frames must be blank
      3. baseline: provision → signed ARM of the blank candidate → PL latch → scores must
         equal the host's base prediction (fabricmap: train [18,22,20,20,20,18])
    Every refusal must happen at the named link; a refused candidate reaching the fabric is KILL.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R / "scripts")); sys.path.insert(0, str(R / "host")); sys.path.insert(0, str(R))
sys.path.insert(0, str(R / "imported/fabricmap/scripts"))
import board_session as bsn  # noqa: E402
import pcap_probe_plan as pp  # noqa: E402
import pcap_probe_runner as pr  # noqa: E402
import run_log as rl  # noqa: E402
import l3_runner as l3  # noqa: E402
import p3_gate as g  # noqa: E402
import p3_oracle as po  # noqa: E402
from validators import records  # noqa: E402

TOOL_VERSION = "l4_runner.py/0.1.0"
RULING_TEXT = "whole-of-probe P3-L4"
CORRUPT_WORD = g.wp.FDRI_DATA_OFFSET + 51      # word 51 of the first target frame (an INIT word)


def illegal_candidate(phen: dict) -> dict[int, list[int]]:
    c = g.known_answer_candidate(phen)
    c[0x00400A20] = list(c[0x00400A20]); c[0x00400A20][3] ^= 1        # a bit outside the whitelist
    return c


def gate_refused_record(phen: dict) -> dict:
    v = g.gate(g.build_streams(illegal_candidate(phen), phen), phen)
    records.validate(v)
    if v["writable"]:
        raise RuntimeError("KILL: the illegal candidate passed the gate")
    return {"stage": "L4_0_gate_refused", "verdict": "REFUSED_AT_LINK_1", "gate_verdict": v,
            "kinds": sorted({f["kind"] for f in v["findings"]}), "board_action": "NONE"}


def blank_candidate(phen: dict) -> dict[int, list[int]]:
    base, roles = g.gc.pinned_frames(phen)
    return {far: list(base[far]) for far, r in roles.items() if r == "target"}


def run_l4(session: bsn.BoardSession, out_dir: Path, ruling: dict, cfg: dict) -> dict:
    manifest, consts = cfg["manifest"], cfg["consts"]
    table = cfg.get("table") or l3.load_p3_table(cfg["bitstream"], manifest)
    phen = g.load_manifest()
    summary = {"tool": TOOL_VERSION, "ruling": ruling, "stages": {}, "outcome": None, "bitstream_sha256": table["sha256"]}
    recs: list[dict] = []

    def finish(rec, name):
        pr.write_record(out_dir, name, rec); summary["stages"][name] = rec.get("verdict")

    try:
        finish(gate_refused_record(phen), "L4_0_gate_refused")
        summary["precheck"] = pr.precheck(session)
        summary["identity"] = session.verify_identity()
        summary["setup_load"] = session.load_carrier(bsn.SETUP_LOAD_CAPABILITY, cfg["bitstream"],
                                                     manifest["bitstream_sha256"], out_dir / "ymodem.log")
        far_sets = {e["far_set"] for e in g.envelopes(phen)}
        # ---- 1. corrupted staged buffer → link 2 STOP, no DMA
        ka = g.build_streams(g.known_answer_candidate(phen), phen)[0]["words"]
        session.authorise(bsn.CONFIG_READ_CAPABILITY)
        l3.ensure_dcache_off(session)
        session.command(f"mw.l {pp.REG['INT_STS']:#010x} {pp.INT_STS_CLEAR_MASK:#010x} 1")
        before = session.read_word(pp.REG["INT_STS"])
        for i, w in enumerate(ka):
            session.command(f"mw.l {l3.WR_BUF + 4 * i:#010x} {w:#010x} 1")
        corrupt = ka[CORRUPT_WORD] ^ 0x8000
        session.command(f"mw.l {l3.WR_BUF + 4 * CORRUPT_WORD:#010x} {corrupt:#010x} 1")
        reread = session.read_words(l3.WR_BUF, len(ka))
        link2 = {"stage": "L4_1_corrupt_stage", "corrupt_word": CORRUPT_WORD, "sent": f"{ka[CORRUPT_WORD]:#010x}",
                 "corrupted_to": f"{corrupt:#010x}", "reread_word": f"{reread[CORRUPT_WORD]:#010x}",
                 "reread_equals_stream": reread == ka, "int_sts_before": f"{before:#010x}"}
        if reread == ka:
            link2["verdict"] = "KILL"; finish(link2, "L4_1_corrupt_stage")
            raise l3.Stop("KILL", "the corrupted buffer re-read as the stream: link 2 cannot see corruption")
        after = session.read_word(pp.REG["INT_STS"])
        link2["int_sts_after"] = f"{after:#010x}"
        link2["dma_happened"] = bool(after & pp.INT_STS_D_P_DONE)
        link2["verdict"] = "REFUSED_AT_LINK_2" if not link2["dma_happened"] else "KILL"
        finish(link2, "L4_1_corrupt_stage")
        if link2["dma_happened"]:
            raise l3.Stop("KILL", "a DMA completed although link 2 refused the buffer")
        # ---- 2. restore to base: three envelopes of the blank candidate, link 2 each, write
        blank = blank_candidate(phen)
        bv = g.gate(g.build_streams(blank, phen), phen)
        if not bv["writable"]:
            raise l3.Stop("GATE_REFUSED", "the blank candidate is not writable")
        for s in g.build_streams(blank, phen):
            far, frames, _ = l3.stage_and_reread(session, s["words"], far_sets)
            wrec = l3.execute_write(session, f"L4_2_restore_write_{s['index']}"); finish(wrec, wrec["stage"])
        read_frames = {}
        for far in sorted(blank):
            rec = l3.readback_frame(session, table, far, blank[far], f"L4_3_restore_read_{far:#010x}")
            finish(rec, rec["stage"])
            read_frames[far] = [int(w, 16) for w in rec["readout"]][pp.FRAME_WORDS:2 * pp.FRAME_WORDS]
        if rl.frames_hash(read_frames) != bv["candidate_sha256"]:
            raise l3.Stop(l3.STOP_LINK3, "restore did not read back as the base")
        summary["restore"] = {"verdict": "RESTORED", "readback_sha256": rl.frames_hash(read_frames)}
        # ---- 3. baseline score: provision, signed ARM of the blank candidate
        prov = cfg["signer"].provision(execute=cfg.get("provision_execute", False), ruling=cfg.get("provision_ruling"))
        summary["provisioning"] = prov
        plane = l3.Plane(session)
        st = plane.read(po.STATUS)
        if not st >> po.ST["key_loaded"] & 1:
            raise l3.Stop("KEY_NOT_LOADED", f"STATUS {st:#010x}")
        tables = po.expected_tables(blank, consts)
        bv = dict(bv, epoch=session.epoch); recs.append(bv)
        arm, score = l3.arm_and_score(plane, cfg["signer"], bv, tables, False)
        arm.pop("_payload", None)
        oracle = {"schema": "oracle_record", "schema_version": "1.0.0",
                  "session": {"boardid": summary["identity"]["parsed"]["boardid"], "epoch": session.epoch, "plmark": session.plmark},
                  "candidate_sha256": bv["candidate_sha256"], "staged_sha256": bv["candidate_sha256"],
                  "staged_stream_sha256": bv["sequence_sha256"], "write": {"envelopes": 3},
                  "readback_sha256": rl.frames_hash(read_frames), "configuration_valid_hw_expected": True}
        records.validate(oracle); recs.append(oracle)
        arm.update(oracle_record_sha256=records.canonical_sha256(oracle), gate_verdict_sha256=records.canonical_sha256(bv), epoch=session.epoch)
        records.validate(arm); recs.append(arm)
        if score is None:
            raise l3.Stop(l3.STOP_ARM, f"the PL refused the baseline ARM: {arm.get('pl_refusal')}")
        score.update(arm_record_sha256=records.canonical_sha256(arm), host_prediction=po.predict_scores(tables, consts))
        score["match"] = score["host_prediction"] == score["scores"]
        records.validate(score); recs.append(score)
        summary["baseline"] = {"scores": score["scores"], "prediction": score["host_prediction"], "match": score["match"]}
        summary["outcome"] = "PASS" if score["match"] else "HOLD: baseline scores differ from the host prediction"
    except l3.Stop as stop:
        if stop.record is not None:
            pr.write_record(out_dir, "stop", stop.record)
        summary["outcome"] = (f"KILL {stop.detail}" if stop.verdict == "KILL" else f"STOP {stop.verdict}: {stop.detail}")
    except (pr.ProbeStop,) as stop:
        summary["outcome"] = f"STOP {stop.verdict}: {stop.detail}"
    except bsn.SessionRefusal as refusal:
        summary["outcome"] = f"REFUSED: {refusal}"
    except Exception as exc:
        import traceback
        summary["outcome"] = f"CRASHED host-side: {type(exc).__name__}: {exc}"; summary["traceback"] = traceback.format_exc()
    finally:
        log = {"schema": "run_log", "schema_version": "1.0.0", "tool": TOOL_VERSION,
               "ruling_sha256": hashlib.sha256(json.dumps(ruling, sort_keys=True).encode()).hexdigest(),
               "records": recs, "epoch_final": session.epoch, "outcome": summary["outcome"]}
        try:
            summary["run_log_validation"] = records.validate_run_log(log)
        except records.RecordError as exc:
            summary["run_log_validation"] = f"REJECTED: {exc}"
            summary["outcome"] = f"KILL run_log rejected: {exc} (was: {summary['outcome']})"
        pr.write_record(out_dir, "run_log", log)
        summary["uart_log"] = session.log; summary["disruptions"] = session.disruptions
        summary["transport_rereads"] = session.rereads; summary["epoch_final"] = session.epoch
        pr.write_record(out_dir, "summary", summary)
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--gate-refused-only", action="store_true", help="host-only: write the link-1 refusal record and exit")
    ap.add_argument("--ruling", type=Path); ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, required=True); ap.add_argument("--bitstream", type=Path)
    ap.add_argument("--key", type=Path, default=Path("/var/lib/p3signer/keys/K.bin"))
    ap.add_argument("--boundary", type=Path); ap.add_argument("--signer-user", default="p3signer")
    ap.add_argument("--provision-ruling", type=Path, default=None); ap.add_argument("--port", default=bsn.PORT)
    a = ap.parse_args(argv)
    phen = g.load_manifest()
    if a.gate_refused_only:
        a.out.mkdir(parents=True, exist_ok=True)
        rec = gate_refused_record(phen); pr.write_record(a.out, "L4_0_gate_refused", rec)
        print("REFUSED_AT_LINK_1:", rec["kinds"], "-> no board action"); return 0
    try:
        if not (a.ruling and a.bitstream and a.boundary):
            raise bsn.SessionRefusal("--ruling, --bitstream and --boundary are required for the on-board session")
        ruling = pr.check_ruling(a.ruling, text=RULING_TEXT)
        if a.out.exists():
            raise bsn.SessionRefusal(f"{a.out} exists; evidence is never replaced")
        if shutil.which("sb") is None:
            raise bsn.SessionRefusal("`sb` is not installed")
        manifest = json.loads(a.manifest.read_text()); records.validate(manifest)
        boundary = json.loads(a.boundary.read_text()); records.boundary_established(boundary, time.time())
        cfg = {"manifest": manifest, "bitstream": a.bitstream, "consts": po.load_constants(),
               "signer": l3.SubprocessSigner(a.key, signer_user=a.signer_user),
               "provision_execute": a.provision_ruling is not None, "provision_ruling": a.provision_ruling}
        cfg["table"] = l3.load_p3_table(a.bitstream, manifest)
    except (bsn.SessionRefusal, pr.ProbeStop, ValueError, records.RecordError, OSError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr); return 2
    consumed = pr.claim_ruling(a.ruling); a.out.mkdir(parents=True)
    l3._install_sigterm()
    outcome = "CRASHED before a summary was written"
    try:
        transport = bsn.SerialTransport(a.port)
        try:
            outcome = run_l4(bsn.BoardSession(transport), a.out, ruling, cfg)["outcome"]
        finally:
            transport.close()
    except bsn.SessionRefusal as exc:
        outcome = f"REFUSED: {exc}"
    finally:
        pr.record_outcome(consumed, outcome)
        if a.provision_ruling:            # the P3-K ruling: the signer consumed it at execution; record the session outcome beside it
            l3._record_pk(a.provision_ruling, outcome)
    print(outcome, file=sys.stderr if outcome != "PASS" else sys.stdout)
    return 0 if outcome == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
