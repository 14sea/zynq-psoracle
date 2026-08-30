#!/usr/bin/env python3
"""L3 diagnostic — localise session #1's LINK3_MISMATCH (`docs/l3_diag_spec.md`).

PCAP phase (this user, the runner), ruling RULING_TEXT:
    setup load
    → env0 write → read A20
    → env1 write → read A20, C1A
    → env2 write → read A20, C1A, C20
    → seal (sha256 of every record) → jtag_request.json
Stop semantics: a link-3 mismatch ends all further PCAP WRITES; the reads of the current
phase are completed, then one closing read of {A20, C1A, C20} (non-destructive), then seal.
JTAG phase (the signer principal, terminal): `host/l3_diag_jtag.py` — the runner asks for it
through sudo and saves the answer as jtag.json.
Adjudication (`adjudicate`): PCAP-after-last-write vs JTAG per FAR → one of
    NO_REPRODUCTION   every PCAP read matched its expectation
    PCAP_READBACK_ZERO PCAP read blank/mismatch but JTAG shows the written content
    FABRIC_BLANK       PCAP and JTAG agree the frame is blank (write cleared/misplaced)
    FABRIC_MISPLACED   JTAG shows candidate content at a FAR that should be base
    DIVERGENT          other PCAP/JTAG disagreement (named)
No ARM, no provisioning, no score. Reads only after the writes the phase table names.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R / "scripts")); sys.path.insert(0, str(R / "host")); sys.path.insert(0, str(R))
sys.path.insert(0, str(R / "imported/fabricmap/scripts"))
import board_session as bsn  # noqa: E402
import pcap_probe_plan as pp  # noqa: E402
import pcap_probe_runner as pr  # noqa: E402
import l3_runner as l3  # noqa: E402
import p3_gate as g  # noqa: E402
from validators import records  # noqa: E402

TOOL_VERSION = "l3_diag_runner.py/0.1.0"
RULING_TEXT = "whole-of-probe P3-L3-diag"
A20, C1A, C20 = 0x00400A20, 0x00400C1A, 0x00400C20
PHASES = [(0, (A20,)), (1, (A20, C1A)), (2, (A20, C1A, C20))]
CLOSING = (A20, C1A, C20)
STAT_CRC_ERROR = 1 << 0


def read_one(session, table, far, expected, name, out_dir, summary):
    """A readback whose STOP is recorded, not raised (the diagnostic wants every read)."""
    try:
        rec = l3.readback_frame(session, table, far, expected, name)
    except l3.Stop as stop:
        rec = stop.record or {"stage": name, "verdict": "NO_RECORD", "detail": stop.detail}
    pr.write_record(out_dir, name, rec); summary["stages"][name] = rec.get("verdict")
    return {"far": f"{far:#010x}", "verdict": rec.get("verdict"), "frame_sha256": rec.get("frame_sha256"),
            "matched_far": rec.get("matched_far"), "nonzero": sum(1 for w in rec.get("readout", [])[101:] if int(w, 16)) if rec.get("readout") else None}


def run_pcap_phase(session: bsn.BoardSession, out_dir: Path, ruling: dict, cfg: dict) -> dict:
    manifest = cfg["manifest"]
    table = cfg.get("table") or l3.load_p3_table(cfg["bitstream"], manifest)
    phen = g.load_manifest()
    cand = g.known_answer_candidate(phen)
    summary = {"tool": TOOL_VERSION, "ruling": ruling, "stages": {}, "phases": [], "outcome": None,
               "bitstream_sha256": table["sha256"], "expected": {f"{far:#010x}": pr.frame_sha256(cand[far]) for far in CLOSING}}
    try:
        streams = g.build_streams(cand, phen)
        if not g.gate(streams, phen)["writable"]:
            raise l3.Stop("GATE_REFUSED", "known answer not writable")
        far_sets = {e["far_set"] for e in g.envelopes(phen)}
        summary["precheck"] = pr.precheck(session)
        summary["identity"] = session.verify_identity()
        summary["setup_load"] = session.load_carrier(bsn.SETUP_LOAD_CAPABILITY, cfg["bitstream"],
                                                     manifest["bitstream_sha256"], out_dir / "ymodem.log")
        mismatch_at = None
        for k, fars in PHASES:
            l3.stage_and_reread(session, streams[k]["words"], far_sets)
            wrec = l3.execute_write(session, f"D_{k}_write_env{k}")
            pr.write_record(out_dir, wrec["stage"], wrec); summary["stages"][wrec["stage"]] = wrec["verdict"]
            reads = [read_one(session, table, far, cand[far], f"D_{k}_read_{far:#010x}", out_dir, summary) for far in fars]
            summary["phases"].append({"phase": k, "write": wrec["verdict"], "reads": reads})
            if any(r["verdict"] != "PASS" for r in reads):
                mismatch_at = k
                break                       # no further PCAP writes
        if mismatch_at is not None:
            summary["closing_reads"] = [read_one(session, table, far, cand[far], f"D_closing_read_{far:#010x}", out_dir, summary) for far in CLOSING]
            summary["outcome"] = f"MISMATCH_REPRODUCED at phase {mismatch_at}; PCAP phase complete, awaiting terminal JTAG"
        else:
            summary["outcome"] = "NO_REPRODUCTION in the PCAP phase; awaiting terminal JTAG"
    except l3.Stop as stop:
        if stop.record is not None:
            pr.write_record(out_dir, "stop", stop.record)
        summary["outcome"] = f"STOP {stop.verdict}: {stop.detail}"
    except pr.ProbeStop as stop:
        summary["outcome"] = f"STOP {stop.verdict}: {stop.detail}"
    except bsn.SessionRefusal as refusal:
        summary["outcome"] = f"REFUSED: {refusal}"
    except Exception as exc:
        import traceback
        summary["outcome"] = f"CRASHED host-side: {type(exc).__name__}: {exc}"; summary["traceback"] = traceback.format_exc()
    finally:
        summary["uart_log"] = session.log; summary["disruptions"] = session.disruptions
        summary["transport_rereads"] = session.rereads; summary["epoch_final"] = session.epoch
        pr.write_record(out_dir, "summary_pcap", summary)
        seal = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out_dir.glob("*.json")) if p.name != "sealed.json"}
        pr.write_record(out_dir, "sealed", seal)
        pr.write_record(out_dir, "jtag_request", {"fars": [f"{f:#010x}" for f in CLOSING], "seal_sha256": hashlib.sha256(json.dumps(seal, sort_keys=True).encode()).hexdigest(),
                                                  "note": "terminal JTAG read by the signer principal; nothing touches the board after it"})
    return summary


def request_jtag(out_dir: Path, signer_user: str = "p3signer") -> dict:
    # absolute path: the sudoers line matches the evidence-directory prefix literally
    p = subprocess.run(["sudo", "-n", "-u", signer_user, sys.executable, str(R / "host/l3_diag_jtag.py"), str(out_dir.resolve())],
                       capture_output=True, text=True, timeout=1000)
    try:
        rec = json.loads(p.stdout)
    except ValueError:
        rec = {"verdict": "NO_RECORD", "rc": p.returncode, "stderr": p.stderr[-600:]}
    pr.write_record(out_dir, "jtag", rec)
    return rec


def adjudicate(summary: dict, jtag: dict) -> dict:
    """Pure. Per FAR: last PCAP verdict/sha vs JTAG sha; expected sha from the candidate."""
    if jtag.get("verdict") != "READ":
        return {"verdict": "HOLD", "detail": f"terminal JTAG did not read: {jtag.get('stop_reason') or jtag.get('stderr')}"}
    last: dict = {}
    for ph in summary.get("phases", []):
        for r in ph["reads"]:
            last[r["far"]] = r
    for r in summary.get("closing_reads", []):
        last[r["far"]] = r
    blank_sha = pr.frame_sha256([0] * 101)
    per_far, kinds = {}, set()
    for far_hex, exp in summary["expected"].items():
        j = jtag["frames"].get(far_hex, {}); jsha = j.get("frame_sha256")
        p = last.get(far_hex, {}); psha = p.get("frame_sha256"); pv = p.get("verdict")
        if pv == "PASS" and jsha == exp:
            kind = "CONSISTENT"
        elif pv != "PASS" and jsha == exp:
            kind = "PCAP_READBACK_ZERO" if psha == blank_sha else "PCAP_READBACK_WRONG"
        elif pv != "PASS" and jsha == blank_sha and exp != blank_sha:
            kind = "FABRIC_BLANK"
        elif exp == blank_sha and jsha not in (blank_sha, None):
            kind = "FABRIC_MISPLACED"
        else:
            kind = "DIVERGENT"
        per_far[far_hex] = {"expected": exp[:16], "pcap": (pv, (psha or "")[:16]), "jtag": (jsha or "")[:16], "kind": kind}
        kinds.add(kind)
    status = jtag.get("config_status"); crc = None if status is None else bool(int(status, 16) & STAT_CRC_ERROR)
    kinds.discard("CONSISTENT")
    verdict = "NO_REPRODUCTION" if not kinds else ("PCAP_READBACK_ZERO" if kinds == {"PCAP_READBACK_ZERO"} else
                                                    "FABRIC_BLANK" if kinds == {"FABRIC_BLANK"} else
                                                    "FABRIC_MISPLACED" if "FABRIC_MISPLACED" in kinds and "PCAP_READBACK_ZERO" not in kinds else "DIVERGENT")
    return {"verdict": verdict, "per_far": per_far, "config_status": status, "crc_error": crc, "kinds": sorted(kinds)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ruling", type=Path); ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, required=True); ap.add_argument("--bitstream", type=Path)
    ap.add_argument("--boundary", type=Path); ap.add_argument("--signer-user", default="p3signer")
    ap.add_argument("--port", default=bsn.PORT)
    ap.add_argument("--jtag", action="store_true", help="phase 2: request the terminal JTAG read from the signer and adjudicate (after the PCAP phase sealed)")
    a = ap.parse_args(argv)
    if a.jtag:
        if not (a.out / "sealed.json").exists():
            print("REFUSED: no sealed PCAP phase in", a.out, file=sys.stderr); return 2
        if (a.out / "jtag.json").exists():
            prev = json.loads((a.out / "jtag.json").read_text())
            if prev.get("verdict") != "NO_RECORD":       # a NO_RECORD never reached the pod: retry is not a second read
                print("REFUSED: jtag.json exists; the terminal read is done once", file=sys.stderr); return 2
            (a.out / "jtag.json").rename(a.out / f"jtag_norecord_{int(time.time())}.json")
        summary = json.loads((a.out / "summary_pcap.json").read_text())
        jt = request_jtag(a.out, a.signer_user)
        verdict = adjudicate(summary, jt)
        pr.write_record(a.out, "diag_verdict", verdict)
        print(json.dumps(verdict, indent=1)); return 0 if verdict["verdict"] != "HOLD" else 1
    try:
        if not (a.ruling and a.bitstream and a.boundary):
            raise bsn.SessionRefusal("--ruling, --bitstream and --boundary are required for the PCAP phase")
        ruling = pr.check_ruling(a.ruling, text=RULING_TEXT)
        if a.out.exists():
            raise bsn.SessionRefusal(f"{a.out} exists; evidence is never replaced")
        if shutil.which("sb") is None:
            raise bsn.SessionRefusal("`sb` is not installed")
        manifest = json.loads(a.manifest.read_text()); records.validate(manifest)
        records.boundary_established(json.loads(a.boundary.read_text()), time.time())
        cfg = {"manifest": manifest, "bitstream": a.bitstream, "table": l3.load_p3_table(a.bitstream, manifest)}
    except (bsn.SessionRefusal, pr.ProbeStop, ValueError, records.RecordError, OSError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr); return 2
    consumed = pr.claim_ruling(a.ruling); a.out.mkdir(parents=True)
    l3._install_sigterm()
    outcome = "CRASHED before a summary was written"
    try:
        transport = bsn.SerialTransport(a.port)
        try:
            outcome = run_pcap_phase(bsn.BoardSession(transport), a.out, ruling, cfg)["outcome"]
        finally:
            transport.close()
    except bsn.SessionRefusal as exc:
        outcome = f"REFUSED: {exc}"
    finally:
        pr.record_outcome(consumed, outcome + " | JTAG phase pending (same ruling)")
    print(outcome); return 0


if __name__ == "__main__":
    sys.exit(main())
