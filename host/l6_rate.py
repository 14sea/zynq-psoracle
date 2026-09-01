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

TOOL_VERSION = "l6_rate.py/0.1.0"
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
}


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


def rate_report(run_log: dict, session: str | None = None, run_log_sha256: str | None = None) -> dict:
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
    rows = []
    for s in candidates:
        t = tim[s]
        arm = records[s].get("arm")
        settle = records[s].get("evidence", {}).get("arm", {}).get("settle", {}).get("polls")
        rows.append({"seq": s, "outcome": records[s]["outcome"], "arm": arm, "wall_s": t["wall"],
                     "period_s": steady.get(s), "breakdown_s": t.get("breakdown"),
                     "hb_count": t.get("hb_count"), "audit_chunks": t.get("audit_chunks"), "settle_polls": settle})
    walls = [r["wall_s"] for r in rows]
    per_vals = [steady[s] for s in candidates if s in steady]
    wall_stats, period_stats = _stats(walls), _stats(per_vals)
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
    return {"schema": "l6_rate_report", "schema_version": "1.0.0", "tool": TOOL_VERSION,
            "session": session, "schedule_mode": run_log.get("app_identity", {}).get("schedule_mode"),
            "epoch_end": run_log["session_summary"]["epoch_end"], "run_log_sha256": run_log_sha256,
            "records": len(seqs), "brackets": sorted(brackets), "candidates": len(candidates),
            "evals_per_hour": evals_per_hour, "cov": period_stats["cov"], "cov_wall": wall_stats["cov"],
            "steady_state_periods": len(per_vals), "transitions_s": transitions,
            "operator_data_sha256": run_log.get("app_identity", {}).get("operator_data_sha256"),
            "failure_rate": (len(failures) / len(rows)) if rows else None, "failures": failures,
            "outcome_counts": counts, "period_s": period_stats, "wall_s": wall_stats, "stages_s": stages,
            "settle_polls": _stats([float(v) for v in settle_vals]) | {"values_are_reads": True},
            "session_span_s": tim[last]["t_rec"] - tim[first]["t_signreq"],
            "clocks": timing.get("clocks"), "per_candidate": rows,
            "definitions": dict(DEFINITIONS)}


def report_sha256(report: dict) -> str:
    return hashlib.sha256(json.dumps(report, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("evidence_dir", type=Path)
    ap.add_argument("--session", choices=SESSIONS, default=None)
    ap.add_argument("--out", type=Path, default=None, help="default: <evidence_dir>/rate_report.json")
    a = ap.parse_args(argv)
    path = a.evidence_dir / "run_log.json"
    try:
        raw = path.read_bytes()
        rep = rate_report(json.loads(raw), a.session, hashlib.sha256(raw).hexdigest())
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
