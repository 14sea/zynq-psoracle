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
                        frames: list[dict], protocol: str = "rec-v3") -> list[str]:
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
    if protocol == "rel-v4":
        import l6_rel as rel                        # indexed heartbeats, a budgeted loss
        out += rel.heartbeat_findings_rel(log, frames)
    else:
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


V05_KEYS = ("nominal_cov_max", "min_clean_periods", "max_recovered_candidates", "max_pull_timeouts",
            "max_bad_frames", "max_fragments")


def calibration_findings_v05(rate_report: dict, pc: dict) -> list[str]:
    """C1/C2 under the v0.5 DRAFT §6.3 (not frozen; the runner selects it only when the
    manifest's prereg version is v0.5): the NOMINAL CoV (periods of candidates without a
    transport recovery) ≤ nominal_cov_max, AND at least min_clean_periods of them, AND the
    recovery indicators within their bounds — every bound named when crossed, so a clean
    nominal spread can never hide an unstable link. The inclusive rate is not bounded here:
    it is what S's N is derived from."""
    out = []
    for k in V05_KEYS:
        if k not in pc:
            out.append(f"v0.5 pass condition {k!r} is not pinned in the manifest")
    if out:
        return out
    nom, rec = rate_report.get("nominal"), rate_report.get("recovery") or {}
    if not isinstance(nom, dict):
        return ["no nominal rate: the report was made without the ledgers (audits.json pulls/recs, timeline frames)"]
    if nom.get("cov") is None:
        out.append("no nominal coefficient of variation could be computed (fewer than two clean periods)")
    elif nom["cov"] > pc["nominal_cov_max"]:
        out.append(f"nominal coefficient of variation {nom['cov']:.3f} > {pc['nominal_cov_max']} "
                   f"(distribution published in rate_report.json)")
    if nom.get("n", 0) < pc["min_clean_periods"]:
        out.append(f"clean steady-state periods {nom.get('n', 0)} < {pc['min_clean_periods']} "
                   f"(excluded: {nom.get('excluded_seqs')})")
    for k, bound in (("candidates_with_recovery", "max_recovered_candidates"), ("pull_timeouts", "max_pull_timeouts"),
                     ("bad_frames", "max_bad_frames"), ("fragments", "max_fragments")):
        v = rec.get(k)
        if v is None:
            out.append(f"recovery indicator {k!r} missing from the rate report")
        elif v > pc[bound]:
            out.append(f"{k} {v} > {pc[bound]} ({bound})")
    return out


def calibration_inputs_findings(report_path, report: dict, required: bool) -> list[str]:
    """v0.5 blocker 2: a calibration report binds the three files it was derived from
    (`inputs`: run_log / audits / timeline sha256); the files beside the report must hash
    to them. `required` (v0.5): a report without `inputs` is refused; under v0.4 a report
    without them is accepted as before, one with them is still verified."""
    import hashlib
    from pathlib import Path
    inputs = report.get("inputs")
    if not isinstance(inputs, dict):
        return ["the calibration report carries no `inputs` (run_log/audits/timeline sha256): made before v0.5"] if required else []
    out = []
    d = Path(report_path).parent
    for k, fname in (("run_log", "run_log.json"), ("audits", "audits.json"), ("timeline", "timeline.json")):
        f = d / fname
        want = inputs.get(k)
        if not f.is_file():
            out.append(f"calibration input {fname} is missing beside the report")
            continue
        got = hashlib.sha256(f.read_bytes()).hexdigest()
        if got != want:
            out.append(f"calibration input {fname} hashes to {got[:16]}…, the report binds {str(want)[:16]}…")
    return out


REL_RECOVERY_KEYS = ("max_sign_retries", "max_ready_resends", "max_ident_repeats", "max_term_retries", "max_done_replays")
REL_TERMINAL = ("STOP_SIGN", "STOP_IDENT")


def unique_ledgers_by_seq(ledgers: list[dict], what: str) -> tuple[dict, list[str], set]:
    """Exactly one ledger per seq (review 2026-09-02, item 1: a dict comprehension kept the
    last of two same-seq ledgers). Returns the by-seq map of the UNIQUE ledgers (a seq with
    more than one is left out), a finding per duplicated seq, and the duplicated seqs."""
    by: dict[int, dict] = {}
    dup: set[int] = set()
    for s in ledgers or []:
        try:
            seq = int(s["seq"])
        except (KeyError, TypeError, ValueError):
            return {}, [f"a {what} ledger without a seq"], set()
        if seq in by or seq in dup:
            dup.add(seq); by.pop(seq, None)
        else:
            by[seq] = s
    return by, [f"seq {q}: more than one {what} ledger (refused, never last-wins)" for q in sorted(dup)], dup


def rel_closure_findings(log: dict, ledgers: dict, pulls: list[dict]) -> list[str]:
    """v0.6 §6.10, machine-enforced (review 2026-09-02, item 5): the rel-v4 transactions
    closed. The identity acknowledged (accepted, no conflict, not refused, ≥ 1 ack); the
    IDENT declaring rel-v4; every record's sign transaction accepted without conflict and
    no sign ledger without a record; no terminal STOP_SIGN/STOP_IDENT record and no
    PROTOCOL end; every pull the host completed CONFIRMED by the board's own record
    (`verified: audited`) — a pull with AUDITWAIT announcements whose record says
    replayed-only is the unconfirmed audit, named with its counts (item 2: the verdict is
    the board's closure evidence, never the wait count); the TERM transaction accepted;
    CLOSE and TERM's closing_control not in conflict (item 7)."""
    out = []
    ident = ledgers.get("ident") or {}
    if not ident.get("accepted"):
        out.append("identity not established: no accepted IDENT ledger")
    if ident.get("refused"):
        out.append("identity refused by the host: " + "; ".join(ident.get("findings") or ["(no finding text)"]))
    if ident.get("conflict"):
        out.append("identity conflict: a second, different IDENT")
    if ident.get("accepted") and int(ident.get("acks_sent", 0)) < 1:
        out.append("identity accepted but never acknowledged")
    proto = (log.get("app_identity") or {}).get("protocol")
    if proto != "rel-v4":
        out.append(f"the IDENT declares wire protocol {proto!r}, not rel-v4")
    records = {r["seq"]: r for r in log["loop_records"]}
    signs, dup, dup_seqs = unique_ledgers_by_seq(ledgers.get("signs") or [], "sign")
    out += dup
    for seq in sorted(records):
        s = signs.get(seq)
        if s is None:
            if seq not in dup_seqs:                     # a duplicated seq is already named once
                out.append(f"seq {seq}: record without a sign ledger")
        elif not s.get("accepted") or s.get("conflict"):
            out.append(f"seq {seq}: sign transaction not accepted or in conflict")
    for seq in sorted((set(signs) | dup_seqs) - set(records)):
        out.append(f"seq {seq}: sign ledger without a record")
    for seq in sorted(records):
        if records[seq]["outcome"] in REL_TERMINAL:
            out.append(f"seq {seq}: terminal {records[seq]['outcome']}")
    end = (log.get("session_summary") or {}).get("epoch_end") or {}
    if end.get("kind") == "PROTOCOL":
        out.append(f"epoch ended PROTOCOL: {end.get('reason')}")
    for p in pulls:
        seq = int(p["seq"])
        r = records.get(seq)
        if r is None:
            continue
        if p.get("done") and r.get("verified") != "audited":
            out.append(f"seq {seq}: the host completed the pull but the board's record is {r.get('verified')!r} — "
                       f"the audit was not confirmed on the board (waits_seen {p.get('waits_seen', 0)}, "
                       f"done_replays {p.get('done_replays', 0)})")
    summary = log.get("session_summary") or {}
    if summary.get("written_by") == "app":
        term = ledgers.get("term")
        if not term or not term.get("accepted") or term.get("conflict"):
            out.append("TERM transaction not accepted (or in conflict)")
        elif int(term.get("acks_sent", 0)) < 1:
            out.append("TERM accepted but never acknowledged")
    if summary.get("written_by") == "app":
        import l6_rel as rel
        out += rel.closing_control_findings(summary)          # §2.6o: the complete closing control, always
    if ledgers.get("closing_conflict"):
        cc = ledgers["closing_conflict"]
        out.append(f"CLOSE and TERM.closing_control disagree: CLOSE {cc.get('close')} vs TERM {cc.get('term')}")
    return out


def rel_control_findings(sign_ledgers: list[dict], armed: bool) -> list[str]:
    """v0.6 §6.12 / §2.6k: the forced SIGNREQ-retry control on seq 1 — the exact shape:
    attempts ["crc", "ok"], one SIGNGET, no replay, accepted, no conflict."""
    if not armed:
        return ["the SIGNREQ-retry control was not armed (flags.bit5)"]
    by, dup, _ = unique_ledgers_by_seq(sign_ledgers, "sign")
    if dup:
        return [f"SIGNREQ-retry control: {d}" for d in dup]     # never judged on a last-wins ledger
    led = by.get(1)
    if led is None:
        return ["no sign ledger for seq 1: the SIGNREQ-retry control was not exercised"]
    shape = [a.get("outcome") for a in led.get("attempts", [])]
    out = []
    if shape != ["crc", "ok"]:
        out.append(f"SIGNREQ-retry control: seq 1 attempts {shape}, the preregistered shape is ['crc', 'ok']")
    if led.get("gets_sent") != 1:
        out.append(f"SIGNREQ-retry control: {led.get('gets_sent')} SIGNGET sent, exactly one is the shape")
    if led.get("replays", 0) != 0:
        out.append(f"SIGNREQ-retry control: {led.get('replays')} cached replays, none is the shape")
    if not led.get("accepted") or led.get("conflict"):
        out.append("SIGNREQ-retry control: seq 1 not accepted or in conflict")
    return out


def rel_recovery_findings(recovery: dict, pc: dict) -> list[str]:
    """v0.6 §6.13: the rel-v4 recovery indicators within their bounds (heartbeats are
    `l6_rel.heartbeat_findings_rel`'s)."""
    out = [f"v0.6 pass condition {k!r} is not pinned in the manifest" for k in REL_RECOVERY_KEYS if k not in pc]
    if out:
        return out
    for key, bound in (("sign_retries", "max_sign_retries"), ("ready_resends", "max_ready_resends"),
                       ("ident_repeats", "max_ident_repeats"), ("term_retries", "max_term_retries"),
                       ("done_replays", "max_done_replays")):
        v = recovery.get(key)
        if v is None:
            out.append(f"recovery indicator {key!r} missing from the rate report")
        elif v > pc[bound]:
            out.append(f"{key} {v} > {pc[bound]} ({bound})")
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


def rec_closure_findings(log: dict, rec_ledgers: list[dict]) -> list[str]:
    """Prereg v0.4 PASS condition 7, machine-enforced (review 2026-09-02, blocker 3): every
    record's transaction was closed by the host's own RECACK. The set of loop-record seqs and
    the set of REC-ledger seqs must be exactly equal; every ledger accepted and without
    conflict, with at least one RECACK actually sent; no ledger without a record (a
    transaction the host never accepted — an exhausted or advanced-without-ACK one) and no
    record without a ledger (a record that reached the log by any path but the transaction).
    Every violation is named by seq."""
    out = []
    rec_seqs = {r["seq"] for r in log["loop_records"]}
    by_seq: dict[int, dict] = {}
    for l in rec_ledgers:
        if l["seq"] in by_seq:
            out.append(f"REC closure: two ledgers for seq {l['seq']}")
        by_seq[l["seq"]] = l
    missing = sorted(rec_seqs - set(by_seq))
    if missing:
        out.append(f"REC closure: records without a transaction ledger: {missing}")
    extra = sorted(set(by_seq) - rec_seqs)
    if extra:
        out.append(f"REC closure: transaction ledgers without a record: {extra}")
    for seq in sorted(rec_seqs & set(by_seq)):
        l = by_seq[seq]
        if not l.get("accepted"):
            out.append(f"REC closure: seq {seq} has a record but its transaction was never accepted")
        if l.get("conflict"):
            out.append(f"REC closure: seq {seq} saw a conflicting duplicate")
        if l.get("acks_sent", 0) < 1:
            out.append(f"REC closure: seq {seq} was never acknowledged by the host (no RECACK sent)")
        if not any(a.get("outcome") == "ok" for a in l.get("attempts", [])):
            out.append(f"REC closure: seq {seq} has no accepted attempt in its ledger")
    return out


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
    # EXACTLY the preregistered shape (review 2026-09-02, blocker 4): the corrupted first
    # transmission, then the accepted resend, nothing else — and exactly one RECGET, the
    # host's. A lost RECACK on seq 1 (a `duplicate` third attempt) or a second RECGET is a
    # different transport event and makes the control's evidence ambiguous: a HOLD, named.
    if outcomes != ["crc", "ok"] or not l["accepted"] or l.get("conflict"):
        return [f"forced REC-retry control not exercised exactly: seq 1 attempts {outcomes}, accepted {l['accepted']}, "
                f"conflict {l.get('conflict', False)} (the preregistered shape is exactly ['crc', 'ok'], accepted)"]
    if l["gets_sent"] != 1:
        return [f"forced REC-retry control: {l['gets_sent']} RECGETs sent for seq 1, the preregistered shape is exactly one"]
    if l.get("acks_sent", 0) < 1:
        return ["forced REC-retry control: seq 1's resend was accepted but never acknowledged (no RECACK sent)"]
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
