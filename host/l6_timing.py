#!/usr/bin/env python3
"""Frame timestamps (prereg §4.1) — the instrument change session 4 showed was missing.

Session 4's evidence carries no per-frame receive time, so the per-candidate rate Claim
B's calibration needs (`claimb_preregistration.md` §6) cannot be derived from it. This
module gives the runner a `Timeline`: every console line is stamped with a monotonic and
a wall-clock receive time as it is read (the raw `console.log` bytes stay verbatim; the
stamped companion is `console.ts.log`), every frame the host sends is stamped too, and
`record_timing` turns the frame sequence into per-record stage boundaries:

    SIGNREQ → reply (host) → HB#1 → HB#2..4 → HB#5..16 → AUDIT×8 → REC
    |  sign  |   stage   | link2+DMA |   link3    |  audit   | ARM+settle+score |

The HB positions are the application's (firmware/p3_app.c): HB#1 after the streams are
built and before the link-2 witness, one after each of the three envelope DMAs, one after
each of the twelve frame readbacks. The breakdown is attributed from the sequence alone,
which `tests/test_l6_timing.py` proves on session 4's real frame order; the fine
breakdown needs the pinned 16 heartbeats and is None otherwise — the wall time is not.

Resolution: the runner polls the port every ~20 ms and stamps every line a poll returned
with that poll's time, so a boundary is known to ±1 poll interval. Rates of many seconds
per candidate are unaffected; the report states the resolution rather than hiding it.
"""
from __future__ import annotations

import sys
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R / "host"))
import l5_notary as n  # noqa: E402

HB_PER_RECORD = 16
AUDIT_CHUNKS = 8
STAGES = ("sign", "stage", "link2_dma", "link3", "audit", "arm_settle_score")
CLOCKS = {"mono": "time.monotonic() on the host, seconds", "wall": "time.time() on the host, seconds since the epoch",
          "resolution_s": "one runner poll interval (~0.02 s): every line a poll returned shares its stamp"}


class Timeline:
    def __init__(self):
        self.lines: list[tuple[float, float, str]] = []      # every console line, stamped
        self.frames: list[dict] = []                          # parsed frames, rx and tx
        self.crc_dropped = 0
        self.bad_frames = 0
        self.crc_dropped_by_type: dict[str, int] = {}   # the type field as received, "?" if unreadable

    def observe(self, line: str, t_mono: float, t_wall: float) -> None:
        self.lines.append((t_mono, t_wall, line))
        if not line.startswith(n.MAGIC):
            return
        try:
            f = n.parse_line(line)
        except n.CrcError:
            self.crc_dropped += 1
            parts = line.split(" ")
            t = parts[1] if len(parts) > 1 and parts[1] in n.APP_TYPES else "?"
            self.crc_dropped_by_type[t] = self.crc_dropped_by_type.get(t, 0) + 1
            self.frames.append({"dir": "rx", "type": "CRC_DROP", "seq": None, "t_mono": t_mono, "t_wall": t_wall,
                                "frame_type": t})
            return
        except n.FrameError:
            self.bad_frames += 1
            self.frames.append({"dir": "rx", "type": "BAD_FRAME", "seq": None, "t_mono": t_mono, "t_wall": t_wall})
            return
        self.frames.append({"dir": "rx", "type": f["type"], "seq": f["seq"], "t_mono": t_mono, "t_wall": t_wall})

    def note_sent(self, mtype: str, seq: int, t_mono: float, t_wall: float) -> None:
        self.frames.append({"dir": "tx", "type": mtype, "seq": seq, "t_mono": t_mono, "t_wall": t_wall})

    def console_ts_log(self) -> bytes:
        return "".join(f"{m:.6f} {w:.6f} {ln}\n" for m, w, ln in self.lines).encode("utf-8", "replace")

    def to_json(self) -> dict:
        return {"schema": "l6_timeline", "schema_version": "1.1.0", "clocks": CLOCKS,
                "crc_dropped": self.crc_dropped, "crc_dropped_by_type": dict(self.crc_dropped_by_type),
                "bad_frames": self.bad_frames, "frames": list(self.frames),
                "note": "this timeline is the ONE inbound ledger and the CRC authority for the session"}


def record_timing(frames: list[dict], seqs: list[int]) -> dict[int, dict]:
    """Per record (monotonic clock): the stage boundaries the frame sequence supports.
    Keys absent from the sequence are None; lists are in arrival order."""
    out: dict[int, dict] = {}
    for seq in seqs:
        t = {"t_signreq": None, "t_reply": None, "t_auditreq": None, "hb": [], "audit": [], "t_rec": None,
             "t_ready": None, "t_done": None, "t_abort": None}
        for f in frames:
            if f["seq"] != seq:
                continue
            if f["dir"] == "rx":
                if f["type"] == n.T_SIGNREQ and t["t_signreq"] is None:
                    t["t_signreq"] = f["t_mono"]
                elif f["type"] == n.T_HB:
                    t["hb"].append(f["t_mono"])
                elif f["type"] == n.T_AUDIT:
                    t["audit"].append(f["t_mono"])
                elif f["type"] == n.T_REC and t["t_rec"] is None:
                    t["t_rec"] = f["t_mono"]
                elif f["type"] == "AUDIT_READY" and t["t_ready"] is None:
                    t["t_ready"] = f["t_mono"]
            else:
                if f["type"] in (n.T_SIGNOK, n.T_SIGNREF) and t["t_reply"] is None:
                    t["t_reply"] = f["t_mono"]
                elif f["type"] == n.T_AUDITREQ and t["t_auditreq"] is None:
                    t["t_auditreq"] = f["t_mono"]
                elif f["type"] == "AUDITDONE" and t["t_done"] is None:
                    t["t_done"] = f["t_mono"]
                elif f["type"] == "AUDITABORT" and t["t_abort"] is None:
                    t["t_abort"] = f["t_mono"]
        t["hb_count"], t["audit_chunks"] = len(t["hb"]), len(t["audit"])
        t["wall"] = (t["t_rec"] - t["t_signreq"]) if t["t_rec"] is not None and t["t_signreq"] is not None else None
        t["breakdown"] = breakdown(t)
        out[seq] = t
    return out


def breakdown(t: dict) -> dict | None:
    """The six stages, from the pinned frame positions; None unless the record has its
    SIGNREQ, the host reply, all 16 heartbeats and its REC (a stopped candidate has fewer
    heartbeats and its wall time is still reported, but not split).

    The audit stage (prereg v0.3 draft §6): under the PULL protocol it is AUDIT_READY →
    AUDITDONE (or AUDITABORT) on the host clock, retries included; under the push
    protocol it stays HB#16 → the last AUDIT chunk. Which one applies is read off the
    frames themselves — a record with a `t_ready` is a pull."""
    if t["t_signreq"] is None or t["t_reply"] is None or t["t_rec"] is None or len(t["hb"]) != HB_PER_RECORD:
        return None
    hb = t["hb"]
    if not (t["t_signreq"] <= t["t_reply"] <= hb[0] <= hb[-1] <= t["t_rec"]):
        return None
    if t["t_ready"] is not None:
        audit_end = t["t_done"] if t["t_done"] is not None else t["t_abort"]
        if audit_end is None:
            audit_end = t["audit"][-1] if t["audit"] else t["t_ready"]
        if not (hb[15] <= t["t_ready"] <= audit_end <= t["t_rec"]):
            return None
        return {"sign": t["t_reply"] - t["t_signreq"], "stage": hb[0] - t["t_reply"],
                "link2_dma": hb[3] - hb[0], "link3": hb[15] - hb[3],
                "audit": audit_end - t["t_ready"],
                "arm_settle_score": t["t_rec"] - audit_end}
    audit_end = t["audit"][-1] if t["audit"] else hb[15]
    if audit_end < hb[15] or audit_end > t["t_rec"]:
        return None
    return {"sign": t["t_reply"] - t["t_signreq"],
            "stage": hb[0] - t["t_reply"],
            "link2_dma": hb[3] - hb[0],
            "link3": hb[15] - hb[3],
            "audit": (t["audit"][-1] - hb[15]) if t["audit"] else 0.0,
            "arm_settle_score": t["t_rec"] - audit_end}


def periods(timing: dict[int, dict]) -> dict[int, float | None]:
    """The loop's inter-proposal interval per seq: t_signreq(seq+1) − t_signreq(seq). This
    is the quantity a rate is made of — it contains the candidate's whole evaluation AND
    the application's work between records (the operator's compute, §5: "operator compute
    time may differ"). None for the last record, which has no successor."""
    out = {}
    for seq in sorted(timing):
        a, b = timing[seq].get("t_signreq"), timing.get(seq + 1, {}).get("t_signreq")
        out[seq] = (b - a) if a is not None and b is not None else None
    return out


def heartbeat_gaps(frames: list[dict]) -> list[dict]:
    """Every gap between consecutive received HB frames — the heartbeat invariant the soak's
    "no heartbeat gap > 20 s" condition is about (L2's guard). HB frames ONLY: a review
    counter-example had heartbeats at 0 s and 40 s with AUDIT/REC traffic in between, and
    an any-frame gap reported 10 s and would have passed it. Other frames are not
    heartbeats; their gaps are `liveness_gaps`, a transport matter."""
    hb = [f for f in frames if f["dir"] == "rx" and f["type"] == n.T_HB]
    return [{"seq_before": hb[i - 1]["seq"], "seq_after": hb[i]["seq"], "gap_s": hb[i]["t_mono"] - hb[i - 1]["t_mono"]}
            for i in range(1, len(hb))]


def heartbeat_count(frames: list[dict]) -> int:
    return sum(1 for f in frames if f["dir"] == "rx" and f["type"] == n.T_HB)


def liveness_gaps(frames: list[dict]) -> list[dict]:
    """Every gap between consecutive received frames of ANY type — what the collector's
    silence rule sees. Reported for the transport record; never the heartbeat invariant."""
    rx = [f for f in frames if f["dir"] == "rx" and f["type"] not in ("CRC_DROP", "BAD_FRAME")]
    return [{"after": rx[i - 1]["type"], "seq": rx[i - 1]["seq"], "gap_s": rx[i]["t_mono"] - rx[i - 1]["t_mono"]}
            for i in range(1, len(rx))]
