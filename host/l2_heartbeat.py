#!/usr/bin/env python3
"""L2 = P2b — the heartbeat invariant, pure (`docs/l2_spec.md`).

The P3 carrier's HEARTBEAT (0x2028) is a free-running 32-bit counter at FCLK0 (+1 per
clock). Between two host reads it must advance by an amount consistent with the host's
elapsed time: not stalled, not run away. The envelope has BOTH bounds, derived (not
measured) from the FCLK0 decode and a pre-registered host-timing allowance:

    ticks ∈ [ f·(Δt − J)·(1 − T),  f·(Δt + J)·(1 + T) ]

f = FCLK0 in Hz (read-only decode, P2's rule), Δt = host monotonic time between the two
`md.l` replies, J = UART/host jitter allowance, T = relative tolerance. Δt must stay well
below the counter's wrap (2^32 / 50 MHz ≈ 85.9 s); longer intervals are refused, never
disambiguated. The no-read control is adjudicated first (P2's R5): if the heartbeat is
outside its envelope with no PCAP activity, the observable is non-discriminating → HOLD.
"""

from __future__ import annotations

WRAP = 1 << 32
J_S = 0.050            # host/UART jitter allowance per interval, derived (two md.l replies)
T_REL = 0.02           # ±2 % clock tolerance (PLL decode vs. actual)
MAX_INTERVAL_S = 60.0  # wrap guard: 2^32 / 50 MHz = 85.9 s


def delta(a: int, b: int) -> int:
    return (b - a) % WRAP


def envelope(fclk0_hz: float, dt_s: float) -> tuple[int, int]:
    if dt_s <= 0 or dt_s > MAX_INTERVAL_S:
        raise ValueError(f"interval {dt_s} s is outside (0, {MAX_INTERVAL_S}]")
    lo = max(0.0, fclk0_hz * (dt_s - J_S) * (1 - T_REL))
    hi = fclk0_hz * (dt_s + J_S) * (1 + T_REL)
    return int(lo), int(hi) + 1


def interval_verdict(fclk0_hz: float, t0: float, hb0: int, t1: float, hb1: int) -> dict:
    dt = t1 - t0
    lo, hi = envelope(fclk0_hz, dt)
    d = delta(hb0, hb1)
    return {"dt_s": round(dt, 6), "ticks": d, "lo": lo, "hi": hi,
            "ok": lo <= d <= hi, "stalled": d == 0, "runaway": d > hi}


def pinned_bounds_verdict(intervals: list[dict], lo_hz: float, hi_hz: float) -> dict:
    """The owner-pinned manifest envelope (ticks/s), applied to every decidable interval on top
    of the derived envelope. Intervals shorter than 2 s are skipped (host jitter dominates)."""
    bad = [v for v in intervals if v["dt_s"] >= 2.0 and not (lo_hz <= v["ticks"] / v["dt_s"] <= hi_hz)]
    return {"lo_hz": lo_hz, "hi_hz": hi_hz, "checked": sum(1 for v in intervals if v["dt_s"] >= 2.0),
            "violations": [{"to": v["to"], "rate_hz": v["ticks"] / v["dt_s"]} for v in bad], "ok": not bad}


def adjudicate(fclk0_hz: float, samples: list[tuple[str, float, int]]) -> dict:
    """samples = [(step, t_host, heartbeat)] in order; samples[0] is the baseline, samples[1]
    the no-read control. HOLD if the control interval fails; STOP naming the first later
    failure; PASS otherwise. Every interval is reported."""
    if len(samples) < 2 or not samples[1][0].startswith(("P2_2_control", "L2_2_control")):
        raise ValueError("the second sample must be the no-read control")
    intervals = []
    for (n0, t0, h0), (n1, t1, h1) in zip(samples, samples[1:]):
        v = interval_verdict(fclk0_hz, t0, h0, t1, h1)
        v["from"], v["to"] = n0, n1
        intervals.append(v)
    if not intervals[0]["ok"]:
        return {"verdict": "CONTROL_UNSTABLE", "at": intervals[0]["to"], "intervals": intervals,
                "detail": "heartbeat outside its envelope with no PCAP activity; non-discriminating"}
    for v in intervals[1:]:
        if not v["ok"]:
            kind = "STALLED" if v["stalled"] else "RUNAWAY" if v["runaway"] else "OUTSIDE_ENVELOPE"
            return {"verdict": "CONTINUITY_VIOLATION", "kind": kind, "at": v["to"], "intervals": intervals,
                    "attributable": True, "detail": f"heartbeat {kind} after PCAP activity, with a stable control"}
    return {"verdict": "PASS", "intervals": intervals, "compared": len(intervals)}
