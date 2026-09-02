#!/usr/bin/env python3
"""The rate report (prereg §4.2): the four numbers Claim B's §6 calibration asks for,
derived from a timed run log — per-candidate wall time and its breakdown, evaluations
per hour, the coefficient of variation, and the failure rate. Pure function over the log;
the CLI reads an evidence directory and writes `rate_report.json` beside it.

    l6_rate.py <evidence_dir> [--session C1|C2|S] [--out rate_report.json]

REFUSES a log without timing (session 4's, for instance): a rate cannot be read off file
mtimes, and the report must not be produced from anything but per-frame stamps.

Definitions (also written into every report):
  candidates      the interior records — every seq except the opening baseline (seq 1)
                  and, on a COMPLETED epoch, the closing baseline (the last seq);
  wall            t_rec − t_signreq of a record (the candidate's evaluation, host-observed);
  period          t_signreq(seq+1) − t_signreq(seq): the inter-proposal interval, i.e. the
                  evaluation PLUS the application's work between records (operator time),
                  counted only when BOTH ends are interior candidates (steady state);
  evals_per_hour  3600 / mean(period) over the candidates that have a successor;
  cov             sample standard deviation / mean, over the same periods (the quantity
                  N is derived from is the one whose spread §6.3 bounds); cov_wall is
                  reported alongside;
  failure         a candidate whose outcome is neither SCORED nor REFUSED_BY_GATE (a gate
                  refusal is the operator's proposal being refused, not the instrument
                  failing); failure_rate = failures / candidates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R / "host"))
import l6_timing as lt  # noqa: E402

TOOL_VERSION = "l6_rate.py/0.3.0"
SESSIONS = ("C1", "C2", "S")
NON_FAILURE = ("SCORED", "REFUSED_BY_GATE")


DEFINITIONS = {
    "candidates": "the interior records: every seq except the opening baseline (seq 1) and, on a COMPLETED epoch, the closing baseline (the last seq)",
    "wall": "t_rec - t_signreq of a record: the candidate's evaluation as the host observed it",
    "period": "t_signreq(seq+1) - t_signreq(seq): the inter-proposal interval = the evaluation plus the application's work between records (operator time); STEADY STATE ONLY: both seq and seq+1 interior candidates (N-1 periods). The opening->first and last->closing transitions are in transitions_s and never in the rate, the CoV or N",
    "evals_per_hour": "3600 / mean(period) over the steady-state periods",
    "cov": "sample standard deviation / mean over the steady-state periods (the quantity N is derived from is the one whose spread prereg §6.3 bounds); cov_wall alongside",
    "operator_data_sha256": "the operator contract (map data + mutation_bits) the session ran under, from the IDENT; a calibration is valid only for the same contract",
    "failure": "a candidate whose outcome is neither SCORED nor REFUSED_BY_GATE; failure_rate = failures / candidates",
    "resolution": "every boundary is known to one runner poll interval (~0.02 s); see timing.clocks",
    "binding": "the image, preregistration, wire protocol, session, schedule mode and master seed the session ran under "
               "(run_log.l6.binding, written by the runner from its own pins); the S runner refuses a calibration whose "
               "binding is not the current pins — a new image or protocol changes the nominal period and needs new C1/C2 "
               "(prereg v0.4)",
    "inclusive": "ALL steady-state periods, recoveries included (a chunk timeout, a re-requested chunk or record, a torn "
                 "line, a CRC drop inside the candidate's window all stay in): evals_per_hour and cov as above. The "
                 "conservative rate: S's N is derived from it (v0.5 draft)",
    "nominal": "the steady-state periods of candidates WITHOUT a transport recovery (no pull retry/timeout/CRC, no REC "
               "retry, no CRC_DROP/BAD_FRAME/FRAGMENT event inside the window): the instrument's nominal spread; its CoV "
               "is bounded only together with a preregistered minimum number of clean periods and the recovery bounds "
               "(v0.5 draft §6.3) — never on its own. Every excluded seq is named",
    "recovery": "the transport-recovery indicators of the session: candidates with a recovery, pull timeouts / retries / "
                "CRC drops, REC retries, bad frames, fragments, stale duplicates, CRC drops in all (the seq-1 control's "
                "deliberate drop counted apart). Bounded by v0.5 draft §6.3 so a nominal CoV cannot hide an unstable link",
    "planning": "candidates × 3600 / (t_rec(last record) − t_signreq(first record)): every candidate the session scored "
                "over EVERYTHING the session took — both brackets, both transitions, every recovery wherever it fell, the "
                "last candidate's included (a recovery on the last candidate lands in the last→closing transition and is "
                "outside every steady-state period; review 2026-09-02). The conservative planning rate: S's N is derived "
                "from it under v0.5 (D-t1), never from the inclusive or nominal rate",
    "inputs": "sha256 of the three evidence files the report was derived from — run_log.json, audits.json, timeline.json — "
              "as written; a calibration pin is verified against all three (v0.5 blocker 2)",
    "ledgers": "nominal, recovery and the per-candidate attribution exist only when BOTH ledgers are supplied and valid: "
               "audits.json with a REC ledger for every record and a completed pull for every audited record, and the "
               "timeline frames with a SIGNREQ for every record; one without the other is refused, never zero-filled "
               "(v0.5 blocker 1)",
}
BINDING_KEYS = ("image_sha256", "prereg_sha256", "protocol", "session", "schedule_mode", "master_seed")
NON_FRAME_EVENTS = ("CRC_DROP", "BAD_FRAME", "FRAGMENT")


class RateError(ValueError):
    """The log cannot yield a rate; the report is not produced."""


def _stats(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "mean": None, "stdev": None, "cov": None, "min": None, "max": None, "median": None}
    mean = statistics.fmean(values)
    # one sample has no spread to report: stdev and cov are None, not 0.0 — a CoV of 0.0
    # from a single period would pass the ≤ 0.10 bound on no evidence (caught in review)
    sd = statistics.stdev(values) if len(values) > 1 else None
    return {"n": len(values), "mean": mean, "stdev": sd, "cov": (sd / mean) if (sd is not None and mean) else None,
            "min": min(values), "max": max(values), "median": statistics.median(values)}


REL_KEYS = ("sign_retries", "ready_resends", "done_replays", "hb_missing")
HB_PER_RECORD = 16


def rel_session_totals(audits: dict | None) -> dict:
    """The rel-v4 session-level indicators (not attributable to a candidate): IDENT
    repeats (every ledger entry after the accepted one, broken lines included) and TERM
    retries (broken TERM lines, re-requests, re-acknowledgements beyond the first)."""
    ident = (audits or {}).get("ident") or {}
    term = (audits or {}).get("term") or {}
    ident_att = ident.get("attempts") or []
    term_att = term.get("attempts") or []
    return {"ident_repeats": max(0, len(ident_att) - 1),
            "term_retries": sum(1 for a in term_att if a.get("outcome") != "ok") + max(0, int(term.get("acks_sent", 0)) - 1)}


def recovery_by_seq(tim: dict[int, dict], seqs: list[int], audits: dict | None, frames: list[dict] | None,
                    control_seq: int | None = 1, records: dict | None = None) -> dict[int, dict]:
    """Per record: the transport recoveries attributed to it (v0.5 draft §6.3). A pull
    ledger's non-ok attempts and timeouts, a REC ledger's non-ok attempts / RECGETs, and
    every CRC_DROP / BAD_FRAME / FRAGMENT event whose stamp lies in [t_signreq(seq),
    t_signreq(seq+1)) — the window whose period the event can lengthen. The forced
    REC-retry control (seq 1's first REC, deliberately corrupted) is attributed as
    `control`, not as a recovery. Stale duplicates are reported, never a recovery by
    themselves (they only follow a timeout)."""
    pulls = {int(p["seq"]): p for p in (audits or {}).get("pulls", [])}
    recs = {int(r["seq"]): r for r in (audits or {}).get("recs", [])}
    signs = {int(x["seq"]): x for x in ((audits or {}).get("signs") or [])}
    hb_seen: dict[int, set] = {}
    for f in frames or []:
        if f.get("dir") == "rx" and f.get("type") == "HB" and isinstance(f.get("hb_i"), int) and f.get("seq") is not None:
            hb_seen.setdefault(f["seq"], set()).add(f["hb_i"])
    out: dict[int, dict] = {}
    ordered = sorted(seqs)
    for i, s in enumerate(ordered):
        r = {"pull_retries": 0, "pull_timeouts": 0, "pull_crc": 0, "pull_malformed": 0, "duplicates": 0,
             "rec_retries": 0, "rec_gets": 0, "crc_drops": 0, "bad_frames": 0, "fragments": 0, "control": 0,
             "sign_retries": 0, "ready_resends": 0, "done_replays": 0, "hb_missing": 0}
        sg = signs.get(s)
        if sg:
            bad_sign = [a for a in sg.get("attempts", []) if a.get("outcome") not in ("ok",)]
            # the forced SIGNREQ-retry control on seq 1 (["crc", "ok"], one GET) is the control, not a recovery
            # one extra wire event per non-ok attempt (a broken request = one SIGNGET, a
            # duplicate request = one cached replay): counted once, never twice
            if s == control_seq and [a.get("outcome") for a in sg.get("attempts", [])][:1] == ["crc"]:
                r["control"] += 1
                bad_sign = bad_sign[1:]
            r["sign_retries"] = len(bad_sign)
        if s in hb_seen and records is not None and (records.get(s) or {}).get("outcome") == "SCORED":
            r["hb_missing"] = HB_PER_RECORD - len({i for i in hb_seen[s] if 0 <= i < HB_PER_RECORD})
        p = pulls.get(s)
        if p:
            bad = [a for a in p.get("attempts", []) if a.get("outcome") != "ok"]
            r["pull_retries"] = len(bad)
            r["pull_timeouts"] = sum(1 for a in bad if a.get("outcome") == "timeout")
            r["pull_crc"] = sum(1 for a in bad if a.get("outcome") == "crc")
            r["pull_malformed"] = sum(1 for a in bad if a.get("outcome") == "malformed")
            r["duplicates"] = len(p.get("duplicates", []))
            r["ready_resends"] = int(p.get("ready_dups", 0))
            r["done_replays"] = int(p.get("done_replays", 0))
        rec_control = sign_control = False
        if sg and s == control_seq and [a.get("outcome") for a in sg.get("attempts", [])][:1] == ["crc"]:
            sign_control = True
        rl = recs.get(s)
        if rl:
            att = [a.get("outcome") if isinstance(a, dict) else a for a in rl.get("attempts", [])]
            bad_att = [a for a in att if a != "ok"]
            if s == control_seq and att[:1] == ["crc"]:
                r["control"] += 1
                rec_control = True
                bad_att = bad_att[1:]
            r["rec_retries"] = len(bad_att)
            r["rec_gets"] = max(0, int(rl.get("gets_sent", 0)) - int(rec_control))   # the control's own RECGET is the control's
        t0 = tim.get(s, {}).get("t_signreq")
        t1 = tim.get(ordered[i + 1], {}).get("t_signreq") if i + 1 < len(ordered) else None
        if frames and t0 is not None:
            for f in frames:
                if f.get("dir") != "rx" or f.get("type") not in NON_FRAME_EVENTS:
                    continue
                tm = f.get("t_mono")
                if tm is None or tm < t0 or (t1 is not None and tm >= t1):
                    continue
                if f["type"] == "CRC_DROP":
                    # each control's own deliberate drop (one REC, one SIGNREQ on seq 1) is the
                    # control's, attributed once per frame type, never a recovery
                    if s == control_seq and f.get("frame_type") == "REC" and rec_control:
                        rec_control = False; continue
                    if s == control_seq and f.get("frame_type") == "SIGNREQ" and sign_control:
                        sign_control = False; continue
                    r["crc_drops"] += 1
                elif f["type"] == "BAD_FRAME":
                    r["bad_frames"] += 1
                else:
                    r["fragments"] += 1
        r["recovered"] = any(r[k] for k in ("pull_retries", "pull_timeouts", "pull_crc", "pull_malformed",
                                             "rec_retries", "rec_gets", "crc_drops", "bad_frames", "fragments",
                                             "sign_retries", "ready_resends", "done_replays", "hb_missing"))
        out[s] = r
    return out


SHA_HEX = 64


def _check_ledgers(records: dict, audits, frames) -> bool:
    """BOTH ledgers or neither (v0.5 blocker 1): one half alone would count the other
    half's faults as zero. Returns False for neither (the v0.4 path: no nominal), True for
    both valid; anything else is refused."""
    if audits is None and frames is None:
        return False
    if audits is None or frames is None:
        raise RateError("half the ledgers: nominal/recovery need BOTH audits (pulls, recs) and the timeline frames — "
                        "one without the other is refused, never taken as zero faults")
    if not isinstance(audits, dict) or not isinstance(audits.get("pulls"), list) or not isinstance(audits.get("recs"), list):
        raise RateError("audits ledger invalid: expected {pulls: [...], recs: [...]} (audits.json)")
    if not isinstance(frames, list) or not frames or not all(
            isinstance(f, dict) and "dir" in f and "type" in f and "t_mono" in f for f in frames):
        raise RateError("timeline frames invalid: expected a non-empty list of {dir, type, t_mono, ...} (timeline.json)")
    seqs = set(records)
    # exactly ONE REC ledger per record and at most ONE pull ledger per seq, no extra seqs
    # (review 2026-09-02, D-t2: a set comparison let a duplicate ledger through and the
    # dict built later would have kept the last one)
    rec_list = [int(r["seq"]) for r in audits["recs"] if isinstance(r, dict) and "seq" in r]
    if len(rec_list) != len(audits["recs"]):
        raise RateError("audits ledger invalid: a REC ledger without a seq")
    dup_rec = sorted({s for s in rec_list if rec_list.count(s) > 1})
    if dup_rec:
        raise RateError(f"audits ledger has more than one REC ledger for seq {dup_rec[:8]}: refused, never last-wins")
    rec_seqs = set(rec_list)
    if rec_seqs != seqs:
        raise RateError(f"audits ledger does not cover the records: REC ledgers for {sorted(rec_seqs)[:8]}…, "
                        f"records {sorted(seqs)[:8]}… (rec-v3 closure: one ledger per record)")
    pull_list = [int(p["seq"]) for p in audits["pulls"] if isinstance(p, dict) and "seq" in p]
    if len(pull_list) != len(audits["pulls"]):
        raise RateError("audits ledger invalid: a pull ledger without a seq")
    dup_pull = sorted({s for s in pull_list if pull_list.count(s) > 1})
    if dup_pull:
        raise RateError(f"audits ledger has more than one pull ledger for seq {dup_pull[:8]}: refused")
    extra = sorted(set(pull_list) - seqs)
    if extra:
        raise RateError(f"audits ledger has pull ledgers for seqs that are not records: {extra[:8]}")
    pulled = {int(p["seq"]) for p in audits["pulls"] if isinstance(p, dict) and p.get("done")}
    audited = {s for s, r in records.items() if r.get("verified") == "audited"}
    if not audited <= pulled:
        raise RateError(f"audits ledger has no completed pull for audited records {sorted(audited - pulled)[:8]}")
    signed = {f.get("seq") for f in frames if f.get("dir") == "rx" and f.get("type") == "SIGNREQ"}
    if not seqs <= signed:
        raise RateError(f"timeline frames carry no SIGNREQ for records {sorted(seqs - signed)[:8]}: not this session's timeline")
    return True


def _check_inputs(inputs_sha256) -> dict:
    if not isinstance(inputs_sha256, dict) or set(inputs_sha256) != {"run_log", "audits", "timeline"}:
        raise RateError("inputs_sha256 must name run_log, audits and timeline (the three files the report is derived from)")
    for k, v in inputs_sha256.items():
        if not (isinstance(v, str) and len(v) == SHA_HEX and all(c in "0123456789abcdef" for c in v)):
            raise RateError(f"inputs_sha256[{k!r}] is not a sha256 hex digest")
    return dict(inputs_sha256)


def rate_report(run_log: dict, session: str | None = None, run_log_sha256: str | None = None,
                audits: dict | None = None, frames: list[dict] | None = None,
                inputs_sha256: dict | None = None) -> dict:
    timing = run_log.get("timing")
    if not isinstance(timing, dict) or not isinstance(timing.get("records"), dict) or not timing["records"]:
        raise RateError("the run log carries no per-frame timing (`timing.records`); a rate cannot be derived "
                        "from it — session 4's evidence is exactly this case (prereg §0/§4.1)")
    if session is not None and session not in SESSIONS:
        raise RateError(f"session {session!r} is not one of {SESSIONS}")
    records = {int(r["seq"]): r for r in run_log["loop_records"]}
    if not records:
        raise RateError("no loop records")
    tim = {int(k): v for k, v in timing["records"].items()}
    missing = [s for s in sorted(records) if s not in tim or tim[s].get("t_signreq") is None or tim[s].get("t_rec") is None]
    if missing:
        raise RateError(f"records without a complete timing record (t_signreq and t_rec): {missing} (prereg §6.3 "
                        f"requires a timing record for every candidate)")
    kind = run_log["session_summary"]["epoch_end"]["kind"]
    seqs = sorted(records)
    first, last = seqs[0], seqs[-1]
    brackets = {first} | ({last} if kind == "COMPLETED" and last != first else set())
    candidates = [s for s in seqs if s not in brackets]
    per = lt.periods(tim)
    interior = set(candidates)
    # steady state: both ends of the transition are interior candidates (N−1 periods); the
    # opening→first and last→closing transitions are reported apart and never enter the
    # rate, the CoV or N (review 2026-09-01: the closing baseline's cost is not a candidate's)
    steady = {s: per[s] for s in candidates if (s + 1) in interior and per.get(s) is not None}
    transitions = {"opening_to_first_s": per.get(first) if candidates and candidates[0] == first + 1 else None,
                   "last_to_closing_s": per.get(candidates[-1]) if candidates and kind == "COMPLETED" else None}
    ledgers_supplied = _check_ledgers(records, audits, frames)
    inputs = None
    if ledgers_supplied:
        inputs = _check_inputs(inputs_sha256)
        if run_log_sha256 is not None and run_log_sha256 != inputs["run_log"]:
            raise RateError("run_log_sha256 disagrees with inputs_sha256['run_log']: the report must name ONE run log file")
        run_log_sha256 = inputs["run_log"]
    recov = recovery_by_seq(tim, seqs, audits, frames, records=records) if ledgers_supplied else {}
    rows = []
    for s in candidates:
        t = tim[s]
        arm = records[s].get("arm")
        settle = records[s].get("evidence", {}).get("arm", {}).get("settle", {}).get("polls")
        rows.append({"seq": s, "outcome": records[s]["outcome"], "arm": arm, "wall_s": t["wall"],
                     "period_s": steady.get(s), "breakdown_s": t.get("breakdown"),
                     "hb_count": t.get("hb_count"), "audit_chunks": t.get("audit_chunks"), "settle_polls": settle,
                     "recovery": recov.get(s), "clean": (not recov[s]["recovered"]) if s in recov else None})
    walls = [r["wall_s"] for r in rows]
    per_vals = [steady[s] for s in candidates if s in steady]
    wall_stats, period_stats = _stats(walls), _stats(per_vals)
    # v0.5 draft: the inclusive rate (every steady-state period) and the nominal one (the
    # periods of candidates without a transport recovery), plus the recovery indicators
    inclusive = {"n": period_stats["n"], "mean_s": period_stats["mean"], "cov": period_stats["cov"],
                 "evals_per_hour": (3600.0 / period_stats["mean"]) if period_stats["mean"] else None}
    if ledgers_supplied:
        excluded = [s for s in candidates if s in steady and recov[s]["recovered"]]
        nom_vals = [steady[s] for s in candidates if s in steady and not recov[s]["recovered"]]
        nom_stats = _stats(nom_vals)
        nominal = {"n": nom_stats["n"], "mean_s": nom_stats["mean"], "cov": nom_stats["cov"],
                   "evals_per_hour": (3600.0 / nom_stats["mean"]) if nom_stats["mean"] else None,
                   "excluded_seqs": excluded, "excluded_periods": len(excluded)}
        keys = ("pull_retries", "pull_timeouts", "pull_crc", "pull_malformed", "duplicates", "rec_retries", "rec_gets",
                "crc_drops", "bad_frames", "fragments") + REL_KEYS
        recovery = {k: sum(recov[s][k] for s in seqs) for k in keys}
        recovery.update(rel_session_totals(audits))
        recovery["candidates_with_recovery"] = sum(1 for s in candidates if recov[s]["recovered"])
        recovery["recovered_seqs"] = [s for s in candidates if recov[s]["recovered"]]
        recovery["control_drops"] = sum(recov[s]["control"] for s in seqs)
        recovery["rx_frames"] = sum(1 for f in (frames or []) if f.get("dir") == "rx" and f.get("type") not in NON_FRAME_EVENTS)
        recovery["ledgers"] = "audits.json pulls/recs + timeline frames"
    else:
        nominal = None
        recovery = {"ledgers": "NOT SUPPLIED: nominal and recovery need audits.json and timeline.json (the runner supplies them; the CLI reads them from the evidence directory)"}
    # the planning rate (D-t1, review 2026-09-02): candidates over the whole bracketed span
    span = tim[last]["t_rec"] - tim[first]["t_signreq"]
    planning = {"candidates": len(candidates), "span_s": span,
                "evals_per_hour": (3600.0 * len(candidates) / span) if span > 0 and candidates else None,
                "definition": "candidates × 3600 / (t_rec(last) − t_signreq(first)); brackets, transitions and every recovery included"}
    failures = [r["seq"] for r in rows if r["outcome"] not in NON_FAILURE]
    counts = {}
    for r in rows:
        counts[r["outcome"]] = counts.get(r["outcome"], 0) + 1
    stages = {}
    for st in lt.STAGES:
        vals = [r["breakdown_s"][st] for r in rows if r["breakdown_s"]]
        stages[st] = _stats(vals)
    settle_vals = [r["settle_polls"] for r in rows if isinstance(r["settle_polls"], int)]
    evals_per_hour = (3600.0 / period_stats["mean"]) if period_stats["mean"] else None
    return {"schema": "l6_rate_report", "schema_version": "1.2.0", "tool": TOOL_VERSION,
            "session": session, "schedule_mode": run_log.get("app_identity", {}).get("schedule_mode"),
            "epoch_end": run_log["session_summary"]["epoch_end"], "run_log_sha256": run_log_sha256,
            "records": len(seqs), "brackets": sorted(brackets), "candidates": len(candidates),
            "evals_per_hour": evals_per_hour, "cov": period_stats["cov"], "cov_wall": wall_stats["cov"],
            "steady_state_periods": len(per_vals), "transitions_s": transitions,
            "inclusive": inclusive, "nominal": nominal, "recovery": recovery, "planning": planning,
            "inputs": inputs,
            "operator_data_sha256": run_log.get("app_identity", {}).get("operator_data_sha256"),
            "failure_rate": (len(failures) / len(rows)) if rows else None, "failures": failures,
            "outcome_counts": counts, "period_s": period_stats, "wall_s": wall_stats, "stages_s": stages,
            "settle_polls": _stats([float(v) for v in settle_vals]) | {"values_are_reads": True},
            "session_span_s": tim[last]["t_rec"] - tim[first]["t_signreq"],
            "clocks": timing.get("clocks"), "per_candidate": rows,
            "binding": binding_of(run_log),
            "definitions": dict(DEFINITIONS)}


def rate_report_from_evidence_dir(evidence_dir, session: str | None = None) -> dict:
    """THE entry point that binds bytes to numbers (review 2026-09-02, D-t2): the report is
    computed from the three files AS READ FROM DISK — the same bytes that are hashed into
    `inputs` — never from in-memory objects. The runner calls this after writing the
    files; the CLI calls it. Both ledgers or neither: with neither file present the v0.4
    report is made (no nominal); with one of the two present the report is refused."""
    d = Path(evidence_dir)
    raw = (d / "run_log.json").read_bytes()
    ap_, tp_ = d / "audits.json", d / "timeline.json"
    audits = frames = inputs = None
    if ap_.exists() or tp_.exists():
        ab = ap_.read_bytes() if ap_.exists() else None
        tb = tp_.read_bytes() if tp_.exists() else None
        audits = json.loads(ab) if ab is not None else None
        frames = json.loads(tb).get("frames") if tb is not None else None
        inputs = {"run_log": hashlib.sha256(raw).hexdigest(),
                  "audits": hashlib.sha256(ab).hexdigest() if ab is not None else None,
                  "timeline": hashlib.sha256(tb).hexdigest() if tb is not None else None}
    return rate_report(json.loads(raw), session, hashlib.sha256(raw).hexdigest(), audits=audits, frames=frames,
                       inputs_sha256=inputs)


def binding_of(run_log: dict) -> dict | None:
    """The run log's own binding (`l6.binding`, written by the runner from the pins it
    verified), copied whole — never reconstructed from the identity frame alone."""
    b = (run_log.get("l6") or {}).get("binding")
    if not isinstance(b, dict):
        return None
    return {k: b.get(k) for k in BINDING_KEYS}


def report_sha256(report: dict) -> str:
    return hashlib.sha256(json.dumps(report, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("evidence_dir", type=Path)
    ap.add_argument("--session", choices=SESSIONS, default=None)
    ap.add_argument("--out", type=Path, default=None, help="default: <evidence_dir>/rate_report.json")
    a = ap.parse_args(argv)
    try:
        rep = rate_report_from_evidence_dir(a.evidence_dir, a.session)
    except (OSError, ValueError, KeyError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    out = a.out or a.evidence_dir / "rate_report.json"
    if out.exists():
        print(f"REFUSED: {out} exists; evidence is never replaced", file=sys.stderr)
        return 2
    out.write_text(json.dumps(rep, indent=2) + "\n")
    print(json.dumps({k: rep[k] for k in ("candidates", "evals_per_hour", "cov", "failure_rate")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
