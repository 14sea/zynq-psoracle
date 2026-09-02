#!/usr/bin/env python3
"""L6 PASS / HOLD conditions as pure functions (prereg §6, D-s4's structural rule).

`host/l6_runner.py` calls these after the validator, the audit policy and the arm check
have accepted the log; each returns a list of findings (strings) and an empty list means
the condition holds. A finding is a HOLD (an instrument matter) — the KILLs are the
validator's `Falsified`, never decided here. Nothing here reads a received frame count
to set a budget; the budget is an input computed before the session.
"""
from __future__ import annotations

import statistics
import sys
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R)); sys.path.insert(0, str(R / "host"))
from validators import audit as au  # noqa: E402
from validators import records  # noqa: E402
import l6_timing as lt  # noqa: E402

BASELINE_SCORES = [18, 22, 20, 20, 20, 18]


def structural_findings(log: dict, chunks: list[dict], requested_audit_seqs: set[int],
                        frames: list[dict]) -> list[str]:
    """D-s4's independent rule: a missing AUDIT, REC or TERM is a structural defect whatever
    the CRC total. REC: every SIGNREQ the host answered has a loop record. AUDIT: every seq
    the host requested (and is SCORED) and every non-SCORED self-report has its chunks,
    complete. TERM: the application's own summary arrived (a collector-written one means
    the TERM never did). HB: exactly 16 per SCORED record (`heartbeat_completeness_findings`)."""
    out = []
    by_seq = {r["seq"]: r for r in log["loop_records"]}
    signreqs = sorted({f["seq"] for f in frames if f["dir"] == "rx" and f["type"] == "SIGNREQ"})
    missing_rec = [s for s in signreqs if s not in by_seq]
    if missing_rec:
        out.append(f"missing REC for seq {missing_rec}")
    try:
        served = au.assemble(chunks) if chunks else {}
    except records.RecordError as exc:
        out.append(f"AUDIT chunks do not reassemble: {exc}")
        served = {}
    for seq in sorted(by_seq):
        r = by_seq[seq]
        cls = records.self_report_class(r)
        needs = (cls == "scored" and seq in requested_audit_seqs) or cls == "auto"
        if needs and seq not in served:
            out.append(f"missing AUDIT for seq {seq} ({r['outcome']}, "
                       f"{'requested' if seq in requested_audit_seqs else '§3a auto'})")
    if log["session_summary"].get("written_by") != "app":
        out.append("missing TERM: the session summary was not the application's")
    out += heartbeat_completeness_findings(log, frames)
    return out


def heartbeat_completeness_findings(log: dict, frames: list[dict]) -> list[str]:
    """The fixed protocol: every SCORED record — the two baselines included — is preceded
    by exactly HB_PER_RECORD (16) heartbeats carrying its seq (one after the streams are
    built, three DMAs, twelve readbacks). Fewer or more is a structural HOLD naming the
    seq. Shared by C1, C2 and S. Review 2026-09-01: a session-wide "at least two HB"
    let a COMPLETED log whose heartbeats stopped after the second one pass every gate.
    A non-SCORED record stopped part-way may carry fewer; more than 16 is anomalous for
    any record."""
    counts: dict[int, int] = {}
    for f in frames:
        if f["dir"] == "rx" and f["type"] == "HB" and f["seq"] is not None:
            counts[f["seq"]] = counts.get(f["seq"], 0) + 1
    out = []
    for r in log["loop_records"]:
        got = counts.get(r["seq"], 0)
        if r["outcome"] == "SCORED" and got != lt.HB_PER_RECORD:
            out.append(f"seq {r['seq']} (SCORED): {got} HB frames, the protocol fixes {lt.HB_PER_RECORD}")
        elif got > lt.HB_PER_RECORD:
            out.append(f"seq {r['seq']} ({r['outcome']}): {got} HB frames exceed the protocol's {lt.HB_PER_RECORD}")
    return out


def baseline_findings(log: dict) -> list[str]:
    """Both baselines exactly the pinned train scores (L5 §5, kept by L6 §6.1)."""
    scored = [r for r in log["loop_records"] if r["outcome"] == "SCORED"]
    if not scored:
        return ["no SCORED record: no baseline to check"]
    out = []
    for name, r in (("opening", scored[0]), ("closing", scored[-1])):
        got = r["evidence"].get("score", {}).get("scores")
        if got != BASELINE_SCORES:
            out.append(f"{name} baseline scores {got} != pinned {BASELINE_SCORES}")
    return out


def calibration_findings(rate_report: dict, cov_max: float) -> list[str]:
    """C1/C2 (§6.3): a timing record for every candidate (the report refuses otherwise)
    and CoV ≤ cov_max — larger is a HOLD with the distribution published (it is: the
    report carries every period)."""
    out = []
    cov = rate_report.get("cov")
    if cov is None:
        out.append("no coefficient of variation could be computed (fewer than two periods)")
    elif cov > cov_max:
        out.append(f"coefficient of variation {cov:.3f} > {cov_max} (distribution published in rate_report.json)")
    return out


def soak_findings(log: dict, frames: list[dict], crc_dropped: int, crc_budget: int,
                  span_s: float, duration_s: float, hb_gap_max_s: float,
                  settle_median_calib: float, settle_bound_factor: int, wall_fraction_min: float) -> list[str]:
    """S (§6.4): no gap > hb_gap_max_s between consecutive HB frames (HB only; at least two
    HB frames or the invariant is unchecked and that is a HOLD), CRC drops within the
    closed-formula budget, wall time ≥ wall_fraction_min × T, every settle.polls within
    [1, settle_bound_factor × the C1/C2 median]."""
    out = []
    n_hb = lt.heartbeat_count(frames)
    if n_hb < 2:
        out.append(f"heartbeat invariant not checkable: {n_hb} HB frame(s) received (an empty set is not a pass)")
    gaps = [g for g in lt.heartbeat_gaps(frames) if g["gap_s"] > hb_gap_max_s]
    if gaps:
        worst = max(gaps, key=lambda g: g["gap_s"])
        out.append(f"{len(gaps)} heartbeat gap(s) > {hb_gap_max_s} s (worst {worst['gap_s']:.1f} s between HB of "
                   f"seq {worst['seq_before']} and seq {worst['seq_after']})")
    if crc_dropped > crc_budget:
        out.append(f"CRC drops {crc_dropped} exceed the D-s4 budget {crc_budget}")
    if span_s < wall_fraction_min * duration_s:
        out.append(f"wall time {span_s:.0f} s < {wall_fraction_min} × T = {wall_fraction_min * duration_s:.0f} s")
    bound = settle_bound_factor * settle_median_calib
    for r in log["loop_records"]:
        polls = r["evidence"].get("arm", {}).get("settle", {}).get("polls")
        if polls is not None and not (1 <= polls <= bound):
            out.append(f"seq {r['seq']}: settle.polls {polls} outside [1, {bound:g}] (10 × calibration median)")
    return out


def crash_audit_count(log: dict, chunks: list[dict], manifest: dict | None) -> tuple[int, str]:
    """The `audited` count a collector-written (CRASHED) summary must carry: the number of
    records whose served words the HOST audit gate verified — `validators.audit.verify`'s
    marks, the same function `validate_standalone_run_log` derives every mark from. Never
    the number of pulls that reached DONE, never the firmware's own mark.

    S #1 (2026-09-01-11): the crash-path summary said `audited 0` while the gate had
    verified 31, so the validator's stated reason was rule (ix) instead of the seq gap.
    If the gate itself refuses the served chunks (they do not reassemble, or a record is
    Falsified), the count is 0 and the note says why — the validator will state that
    refusal, which is then the true first reason."""
    from validators import audit as au
    try:
        marks, _ = au.verify(log, chunks, manifest)
    except records.RecordError as exc:
        return 0, f"the host audit gate refused the served words: {exc}"
    n = sum(1 for m in marks.values() if m == "audited")
    return n, "host audit gate marks (validators.audit.verify)"


def rec_control_findings(rec_ledgers: list[dict], armed: bool) -> list[str]:
    """The forced REC-retry control (rec-v3, prereg v0.4): when the identity page armed it,
    the opening baseline's record (seq 1) must show exactly the retry on the wire — the
    first transmission CRC-failed, then the byte-identical resend accepted — so that every
    session proves the real retry within its first seconds. A session armed with the
    control whose ledger does not show that is a HOLD: the control was not exercised, and
    nothing else in the session says the retry path works. Unarmed sessions are not judged
    here (an unarmed session under v0.4 is itself refused by the runner)."""
    if not armed:
        return []
    by_seq = {l["seq"]: l for l in rec_ledgers}
    l = by_seq.get(1)
    if l is None:
        return ["forced REC-retry control: no REC transaction ledger for seq 1"]
    outcomes = [a["outcome"] for a in l["attempts"]]
    if outcomes[:2] != ["crc", "ok"] or not l["accepted"]:
        return [f"forced REC-retry control not exercised: seq 1 attempts {outcomes}, accepted {l['accepted']} "
                f"(expected a CRC-failed first transmission, then the accepted resend)"]
    if l["gets_sent"] < 1:
        return ["forced REC-retry control: the host never asked for the resend (RECGET), the retry was not the host's"]
    return []


def median_settle_polls(log: dict) -> float | None:
    polls = [r["evidence"]["arm"]["settle"]["polls"] for r in log["loop_records"]
             if "arm" in r.get("evidence", {}) and "settle" in r["evidence"]["arm"]]
    return statistics.median(polls) if polls else None


def median_settle_polls_from_report(rate_report: dict) -> float | None:
    """The calibration median the soak's settle bound is built from (§6.4), read off the
    C1/C2 rate report's own `settle_polls` statistics."""
    sp = rate_report.get("settle_polls") or {}
    return sp.get("median")
