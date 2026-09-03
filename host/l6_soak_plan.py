#!/usr/bin/env python3
"""The soak's N against T — the policy-matched planning rate (v0.7 CANDIDATE, after S #2).

What S #1 and S #2 showed. N = ⌊0.9 × min(planning_C1, planning_C2) × T⌋ (D-s3) takes the
calibrations' planning rates, measured under the ALL-SELF-REPORTING policy where every
record carries an audit stage (≈ 0.48 s of a ≈ 1.03 s period). The soak runs under the
SAMPLED policy: only every 16th record (plus the brackets) is audited, so its pace is
≈ 0.55 s per record — 6522.4 evals/h in S #2 (143 inter-record intervals / 78.928 s),
7230 in S #1 — and an N sized from ≈ 3370 evals/h finishes a "2 h" soak in ≈ 56 min,
failing §6 item 4's wall time ≥ 0.9 T by construction.

What this module computes — from the two PINNED calibration reports and the run logs
they were derived from (their sha256 are the report's `inputs`), never from a soak:

  * the policy-matched rate under `n_rule` ∈ RULES, each an explicit formula:
      planning              — D-s3 as frozen in v0.6 (the control: what S #2 ran with)
      policy_matched_period — 3600 / mean_i(period_i − (1 − f) × audit_i) over the
                              steady-state periods (t_signreq(i+1) − t_signreq(i))
      policy_matched_wall   — 3600 / mean_i(wall_i − (1 − f) × audit_i) over the
                              candidates' wall times (t_signreq(i) → t_rec(i))
      policy_matched_span   — candidates × 3600 / (span − (1 − f) × Σ_i audit_i)
    where audit_i = t_done(i) − t_ready(i) (the pull's audit stage on the host clock) and
    f = the fraction of the soak's records that carry an audit stage under the sampled
    policy, |sampled_audit_seqs(N)| / (N + 2), solved by fixed point with N (f ≈ 1/16);
  * N = ⌊0.9 × min(rate_A, rate_B) × T⌋ with the unrounded product published beside
    the floor (owner 2026-09-03: 6952.2375… gives 12514, the rounded label 6952 gives
    12513 — N is never derived from a rounded value);
  * the POST-HOC validation gate against the recorded soak pace(s): N × interval_obs
    must lie within [0.9 T, timeout) — the pace of S #1 / S #2 is used ONLY to validate a
    candidate N, never as an input to it (owner 2026-09-03).

Nothing here is a frozen rule: v0.6 is frozen with `planning`; the manifest's
`sessions.S.n_rule` names the rule the runner applies under v0.7, and the owner freezes it.
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R / "host"))
import l6_schedule as ls  # noqa: E402

RULES = ("planning", "policy_matched_period", "policy_matched_wall", "policy_matched_span")
# Which arm sizes N (owner's ruling 2026-09-03). `planning` reproduces v0.6 exactly, and
# v0.6 used min(rate) — that is what S #2 ran with, kept here as the control. Every
# policy-matched rule uses the FASTER arm: min() is right for a timeout (the slow arm must
# fit) but wrong for a wall-time floor — a soak that runs near the faster arm finishes a
# min-sized N too early and fails `wall ≥ 0.9 T` by construction. The timeout is always
# derived from the slower arm (`l6_schedule.session_timeout_s` takes min internally).
ARM_FOR_RULE = {"planning": "min", "policy_matched_period": "max",
                "policy_matched_wall": "max", "policy_matched_span": "max"}
DEFAULT_T_S = 7200.0
FIXED_POINT_ROUNDS = 8


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_fraction(n: int, every: int = ls.AUDIT_EVERY) -> float:
    """The fraction of a soak's N + 2 records that carry an audit stage under the sampled
    policy (every `every`-th seq + first/last candidate + both baselines)."""
    return len(ls.sampled_audit_seqs(n, every)) / (n + 2)


def candidate_timing(run_log: dict) -> list[dict]:
    """Per candidate (brackets excluded): period (steady-state), wall, audit stage — from the
    run log's timing records; only records with a complete breakdown (16 HB, a pull with
    its DONE) count, as the rate report's stage statistics do."""
    tim = {int(k): v for k, v in run_log["timing"]["records"].items()}
    kind = run_log["session_summary"]["epoch_end"]["kind"]
    seqs = sorted(tim)
    first, last = seqs[0], seqs[-1]
    brackets = {first} | ({last} if kind == "COMPLETED" and last != first else set())
    cands = [s for s in seqs if s not in brackets]
    interior = set(cands)
    rows = []
    for s in cands:
        t = tim[s]
        if t.get("t_signreq") is None or t.get("t_rec") is None or t.get("t_ready") is None or t.get("t_done") is None:
            continue
        nxt = tim.get(s + 1, {}).get("t_signreq")
        period = (nxt - t["t_signreq"]) if (nxt is not None and (s + 1) in interior) else None
        rows.append({"seq": s, "wall": t["t_rec"] - t["t_signreq"], "audit": t["t_done"] - t["t_ready"], "period": period})
    return rows


def policy_matched_rates(run_log: dict, f: float) -> dict:
    """Every RULES rate (unrounded) for one calibration at audit fraction f."""
    rows = candidate_timing(run_log)
    if not rows:
        raise ValueError("no candidate with a complete pull timing record")
    steady = [r for r in rows if r["period"] is not None]
    tim = {int(k): v for k, v in run_log["timing"]["records"].items()}
    seqs = sorted(tim)
    span = tim[seqs[-1]]["t_rec"] - tim[seqs[0]]["t_signreq"]
    kind = run_log["session_summary"]["epoch_end"]["kind"]
    ncand = len(seqs) - (2 if kind == "COMPLETED" else 1)
    mean_period_adj = sum(r["period"] - (1 - f) * r["audit"] for r in steady) / len(steady)
    mean_wall_adj = sum(r["wall"] - (1 - f) * r["audit"] for r in rows) / len(rows)
    audit_sum = sum(r["audit"] for r in rows)
    return {"planning": 3600.0 * ncand / span,
            "policy_matched_period": 3600.0 / mean_period_adj,
            "policy_matched_wall": 3600.0 / mean_wall_adj,
            "policy_matched_span": 3600.0 * ncand / (span - (1 - f) * audit_sum),
            "inputs": {"candidates": ncand, "steady_periods": len(steady), "rows": len(rows), "span_s": span,
                       "mean_period_s": sum(r["period"] for r in steady) / len(steady),
                       "mean_wall_s": sum(r["wall"] for r in rows) / len(rows),
                       "mean_audit_s": audit_sum / len(rows), "audit_fraction": f}}


def soak_n_for_rule(rule: str, logs: dict, duration_s: float = DEFAULT_T_S) -> dict:
    """N under `rule` from the two calibration run logs ({"C1": log, "C2": log}); the audit
    fraction and N solved together (fixed point); every intermediate unrounded."""
    if rule not in RULES:
        raise ValueError(f"n_rule {rule!r} is not one of {RULES}")
    f = audit_fraction(int(ls.SOAK_FRACTION * 3400 * duration_s / 3600))     # a first guess only; iterated below
    trace = []
    n = None
    for _ in range(FIXED_POINT_ROUNDS):
        rates = {k: policy_matched_rates(logs[k], f) for k in ("C1", "C2")}
        rate_a, rate_b = rates["C1"][rule], rates["C2"][rule]
        sizing = (min if ARM_FOR_RULE[rule] == "min" else max)(rate_a, rate_b)
        product = ls.SOAK_FRACTION * sizing * duration_s / 3600.0
        n_new = math.floor(product)
        trace.append({"f": f, "rate_C1": rate_a, "rate_C2": rate_b, "product": product, "n": n_new})
        f_new = audit_fraction(n_new)
        if n_new == n and abs(f_new - f) < 1e-12:
            break
        n, f = n_new, f_new
    last = trace[-1]
    return {"rule": rule, "duration_s": duration_s, "n": last["n"], "unrounded": last["product"],
            "rate_C1": last["rate_C1"], "rate_C2": last["rate_C2"], "min_rate": min(last["rate_C1"], last["rate_C2"]),
            "sizing_arm": ARM_FOR_RULE[rule],
            "sizing_rate": (min if ARM_FOR_RULE[rule] == "min" else max)(last["rate_C1"], last["rate_C2"]),
            "audit_fraction": last["f"], "sampled_audits": len(ls.sampled_audit_seqs(last["n"])),
            "fixed_point_rounds": len(trace), "trace": trace,
            "per_calibration": {k: rates[k]["inputs"] for k in ("C1", "C2")}}


def observed_interval_s(soak_run_log: dict, exclude_seqs=(1,)) -> dict:
    """A recorded soak's pace — post-hoc validation input only, never an input to N.

    `exclude_seqs` drops seq 1 by default: its period carries the two FORCED retry controls
    (§2.6c and §2.6k corrupt the first transmission of seq 1's REC and SIGNREQ on purpose),
    so it is not the loop's pace (owner's review 2026-09-03).

    Also reported, for the normalisation the gate applies: the mean audit stage measured in
    the same soak, and the audit fraction the soak was PLANNED at (|sampled_audit_seqs(N)| /
    (N + 2)). The PLANNED fraction is the right one — a prefix of a soak over-samples audits,
    because seq 1 and seq 2 are both on the sampled schedule, so the realized fraction of an
    early crash (10/143 in S #2) is not the fraction a whole session would run at."""
    tim = {int(k): v for k, v in soak_run_log["timing"]["records"].items()}
    seqs = sorted(s for s in tim if tim[s].get("t_signreq") is not None)
    kept = [s for s in seqs if s not in set(exclude_seqs)]
    if len(kept) < 2:
        raise ValueError("fewer than two timed records after the exclusions")
    span = tim[kept[-1]]["t_signreq"] - tim[kept[0]]["t_signreq"]
    aud = [tim[s]["t_done"] - tim[s]["t_ready"] for s in kept
           if tim[s].get("t_done") is not None and tim[s].get("t_ready") is not None]
    planned_n = (soak_run_log.get("l6") or {}).get("n")
    return {"records": len(seqs), "excluded_seqs": sorted(set(exclude_seqs) & set(seqs)),
            "records_used": len(kept), "intervals": len(kept) - 1, "span_s": span,
            "interval_s": span / (len(kept) - 1), "evals_per_hour": 3600.0 * (len(kept) - 1) / span,
            "audited_in_span": len(aud), "mean_audit_s": (sum(aud) / len(aud)) if aud else None,
            "planned_n": planned_n,
            "planned_audit_fraction": audit_fraction(planned_n) if isinstance(planned_n, int) and planned_n >= 1 else None,
            "protocol": (soak_run_log.get("app_identity") or {}).get("protocol"),
            "schedule_mode": (soak_run_log.get("app_identity") or {}).get("schedule_mode")}


def validation_gate(n: int, rate_a: float, rate_b: float, duration_s: float, observed: dict,
                    wall_fraction_min: float = 0.9, target_audit_fraction: float | None = None) -> dict:
    """Would a soak of N at the RECORDED pace satisfy wall time ≥ wall_fraction_min × T and
    finish before the runner's timeout? The observed pace validates N; it is not an input.

    The pace is normalised to the candidate's own sampled-audit fraction before it is used:
    a session that audits a smaller share of its records spends less time in the audit stage
    per record, so
        interval_normalised = interval_observed − (f_planned(soak) − f_target) × mean_audit_s
    with both fractions PLANNED (see `observed_interval_s`) and `mean_audit_s` measured in
    the same soak. With no target fraction the raw interval is used and the report says so."""
    timeout = ls.session_timeout_s(n, rate_a, rate_b)
    raw = observed["interval_s"]
    adj = 0.0
    if target_audit_fraction is not None and observed.get("planned_audit_fraction") is not None \
            and observed.get("mean_audit_s") is not None:
        adj = (observed["planned_audit_fraction"] - target_audit_fraction) * observed["mean_audit_s"]
    interval = raw - adj
    predicted = n * interval
    return {"n": n, "observed_interval_s": raw, "normalised_interval_s": interval,
            "audit_normalisation_s": adj, "target_audit_fraction": target_audit_fraction,
            "soak_planned_audit_fraction": observed.get("planned_audit_fraction"),
            "mean_audit_s": observed.get("mean_audit_s"), "excluded_seqs": observed.get("excluded_seqs"),
            "predicted_wall_s": predicted,
            "wall_floor_s": wall_fraction_min * duration_s, "timeout_s": timeout,
            "wall_ok": predicted >= wall_fraction_min * duration_s, "timeout_ok": predicted < timeout,
            "pass": predicted >= wall_fraction_min * duration_s and predicted < timeout,
            "margin_over_floor_s": predicted - wall_fraction_min * duration_s}


def comparison(logs: dict, soaks: dict, duration_s: float = DEFAULT_T_S, wall_fraction_min: float = 0.9,
               protocol: str | None = None) -> dict:
    """The N/T table: every rule × every recorded soak pace. Soaks under `protocol` gate;
    the others are computed and marked informational."""
    out = {"duration_s": duration_s, "wall_fraction_min": wall_fraction_min, "protocol": protocol, "rules": {}}
    for rule in RULES:
        plan = soak_n_for_rule(rule, logs, duration_s)
        gates = {}
        for name, obs in soaks.items():
            g = validation_gate(plan["n"], plan["rate_C1"], plan["rate_C2"], duration_s, obs, wall_fraction_min,
                                target_audit_fraction=plan["audit_fraction"])
            g["gates"] = protocol is None or obs.get("protocol") == protocol
            g["protocol"] = obs.get("protocol")
            gates[name] = g
        plan["gates"] = gates
        gating = [g for g in gates.values() if g["gates"]]
        plan["gate_pass_all"] = bool(gating) and all(g["pass"] for g in gating)
        plan["gating_soaks"] = [k for k, g in gates.items() if g["gates"]]
        out["rules"][rule] = plan
    out["observed"] = soaks
    return out


def load_pinned(l6m: dict, root: Path = R) -> tuple[dict, dict]:
    """The two pinned calibrations' reports and run logs, each verified against the pin:
    the report bytes hash to `calibration.<k>.rate_report_sha256`, the run log beside it
    hashes to the report's `inputs.run_log`."""
    reports, logs = {}, {}
    for k in ("C1", "C2"):
        pin = l6m["calibration"][k]
        rp = root / pin["evidence"]
        if _sha(rp) != pin["rate_report_sha256"]:
            raise ValueError(f"{k}: {pin['evidence']} does not hash to the pin")
        rep = json.loads(rp.read_text())
        lp = rp.parent / "run_log.json"
        if _sha(lp) != rep["inputs"]["run_log"]:
            raise ValueError(f"{k}: run_log.json beside the report does not hash to the report's inputs")
        reports[k], logs[k] = rep, json.loads(lp.read_text())
    return reports, logs


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--l6-manifest", type=Path, default=R / "manifests/l6_manifest.json")
    ap.add_argument("--soak", action="append", default=[], help="evidence dir of a recorded soak (validation only)")
    ap.add_argument("--duration-s", type=float, default=DEFAULT_T_S)
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args(argv)
    l6m = json.loads(a.l6_manifest.read_text())
    reports, logs = load_pinned(l6m)
    soaks = {}
    for d in a.soak:
        d = Path(d)
        log = json.loads((d / "run_log.json").read_text())
        soaks[d.name] = dict(observed_interval_s(log), run_log_sha256=_sha(d / "run_log.json"))
    table = comparison(logs, soaks, a.duration_s, l6m["pass_conditions"]["wall_fraction_min"],
                       protocol=l6m["pinned_at_build"].get("protocol"))
    table["calibration_pins"] = {k: {"rate_report_sha256": l6m["calibration"][k]["rate_report_sha256"],
                                     "inputs": reports[k]["inputs"]} for k in ("C1", "C2")}
    text = json.dumps(table, indent=2)
    if a.out:
        a.out.write_text(text + "\n")
    for rule, plan in table["rules"].items():
        print(f"{rule:24s} rate_C1 {plan['rate_C1']:.6f} rate_C2 {plan['rate_C2']:.6f} product {plan['unrounded']:.6f} "
              f"N {plan['n']} ({plan['sizing_arm']}) audits {plan['sampled_audits']} f {plan['audit_fraction']:.6f} "
              + " ".join(f"{k}:{'PASS' if g['pass'] else 'FAIL'}({g['predicted_wall_s']:.0f}s{'' if g['gates'] else ', informational: ' + str(g['protocol'])})"
                         for k, g in plan["gates"].items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
