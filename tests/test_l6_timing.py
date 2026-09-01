"""host/l6_timing.py — per-frame timestamps and the stage boundaries they support.

The attribution test runs over session 4's REAL console frame order (read-only) with
synthetic monotone stamps: it proves the boundaries the prereg names (SIGNREQ → reply →
HB×16 → AUDIT×8 → REC) are recoverable from the sequence the board actually emits, not
from a sequence this module imagined."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R)); sys.path.insert(0, str(R / "host"))
import l5_notary as n  # noqa: E402
import l6_timing as lt  # noqa: E402

S4 = R / "evidence/l5_17A6_2026-09-01-04/console.log"
TOKEN = "ab" * 16


def frames_for(seq: int, t0: float, reply=True, hb=16, audit=8, rec=True) -> list[dict]:
    """A synthetic candidate at 1 s per event: SIGNREQ, reply, HB×hb, AUDIT×audit, REC."""
    t = t0
    out = [{"dir": "rx", "type": n.T_SIGNREQ, "seq": seq, "t_mono": t, "t_wall": t + 1e9}]
    if reply:
        t += 1; out.append({"dir": "tx", "type": n.T_SIGNOK, "seq": seq, "t_mono": t, "t_wall": t + 1e9})
    for _ in range(hb):
        t += 1; out.append({"dir": "rx", "type": n.T_HB, "seq": seq, "t_mono": t, "t_wall": t + 1e9})
    for _ in range(audit):
        t += 1; out.append({"dir": "rx", "type": n.T_AUDIT, "seq": seq, "t_mono": t, "t_wall": t + 1e9})
    if rec:
        t += 1; out.append({"dir": "rx", "type": n.T_REC, "seq": seq, "t_mono": t, "t_wall": t + 1e9})
    return out


class TimelineStamps(unittest.TestCase):
    def test_every_line_is_stamped_and_raw_bytes_are_not_the_stamped_log(self):
        tl = lt.Timeline()
        good = n.build_line(n.T_HB, 3, TOKEN).rstrip("\n")
        tl.observe("## Starting application", 1.0, 100.0)
        tl.observe(good, 1.5, 100.5)
        tl.observe(good[:-1] + ("0" if good[-1] != "0" else "1"), 2.0, 101.0)   # CRC broken
        tl.observe("P3L5 nonsense", 2.5, 101.5)
        self.assertEqual(len(tl.lines), 4)
        self.assertEqual([f["type"] for f in tl.frames], [n.T_HB, "CRC_DROP", "BAD_FRAME"])
        self.assertEqual((tl.crc_dropped, tl.bad_frames), (1, 1))
        ts = tl.console_ts_log().decode()
        self.assertTrue(ts.startswith("1.000000 100.000000 ## Starting application\n"))
        self.assertIn("1.500000 100.500000 P3L5 HB 3", ts)

    def test_sent_frames_are_stamped_with_direction(self):
        tl = lt.Timeline()
        tl.note_sent(n.T_SIGNOK, 4, 7.0, 107.0)
        self.assertEqual(tl.frames[0], {"dir": "tx", "type": "SIGNOK", "seq": 4, "t_mono": 7.0, "t_wall": 107.0})
        self.assertEqual(tl.to_json()["clocks"], lt.CLOCKS)


class StageAttribution(unittest.TestCase):
    def test_breakdown_from_a_synthetic_sequence_is_exact(self):
        t = lt.record_timing(frames_for(2, 10.0), [2])[2]
        self.assertEqual((t["hb_count"], t["audit_chunks"]), (16, 8))
        self.assertEqual(t["wall"], 26.0)
        # sign 1 (SIGNREQ→reply), stage 1 (reply→HB1), link2_dma 3 (HB1→HB4), link3 12 (HB4→HB16),
        # audit 8 (HB16→AUDIT8), arm_settle_score 1 (AUDIT8→REC)
        self.assertEqual(t["breakdown"], {"sign": 1.0, "stage": 1.0, "link2_dma": 3.0, "link3": 12.0,
                                          "audit": 8.0, "arm_settle_score": 1.0})
        self.assertAlmostEqual(sum(t["breakdown"].values()), t["wall"])

    def test_no_audit_attributes_arm_from_the_last_heartbeat(self):
        t = lt.record_timing(frames_for(5, 0.0, audit=0), [5])[5]
        self.assertEqual(t["breakdown"]["audit"], 0.0)
        self.assertEqual(t["breakdown"]["arm_settle_score"], 1.0)

    def test_a_stopped_candidate_keeps_its_wall_time_but_no_fine_breakdown(self):
        t = lt.record_timing(frames_for(3, 0.0, hb=4, audit=8), [3])[3]
        self.assertEqual(t["wall"], 14.0)
        self.assertIsNone(t["breakdown"])

    def test_missing_rec_yields_no_wall_time(self):
        t = lt.record_timing(frames_for(3, 0.0, rec=False), [3])[3]
        self.assertIsNone(t["wall"]); self.assertIsNone(t["breakdown"])

    def test_periods_are_inter_proposal_intervals(self):
        fr = frames_for(1, 0.0) + frames_for(2, 30.0) + frames_for(3, 65.0)
        tim = lt.record_timing(fr, [1, 2, 3])
        self.assertEqual(lt.periods(tim), {1: 30.0, 2: 35.0, 3: None})

    def test_session_4s_real_frame_order_supports_the_attribution(self):
        """Every one of the ten candidates on the board emitted, in order, SIGNREQ, 16 HB,
        8 AUDIT, REC — so a stamped run of the same firmware yields all six stages."""
        tl = lt.Timeline()
        t = 0.0
        for raw in S4.read_bytes().split(b"\n"):
            line = raw.decode("ascii", "replace").rstrip("\r")
            t += 0.1
            tl.observe(line, t, t + 1e9)
            if line.startswith(f"{n.MAGIC} {n.T_SIGNREQ} "):
                tl.note_sent(n.T_SIGNOK, n.parse_line(line)["seq"], t + 0.05, t + 1e9 + 0.05)
        self.assertEqual((tl.crc_dropped, tl.bad_frames), (0, 0))
        tim = lt.record_timing(tl.frames, list(range(1, 11)))
        for seq, tt in tim.items():
            self.assertEqual((tt["hb_count"], tt["audit_chunks"]), (16, 8), seq)
            self.assertIsNotNone(tt["breakdown"], seq)
            self.assertTrue(all(v >= 0 for v in tt["breakdown"].values()), seq)
            self.assertAlmostEqual(sum(tt["breakdown"].values()), tt["wall"], msg=seq)
        self.assertTrue(all(v is not None for s, v in lt.periods(tim).items() if s < 10))

    def test_heartbeat_gaps_cover_every_received_frame(self):
        fr = frames_for(1, 0.0)
        gaps = lt.heartbeat_gaps(fr)
        self.assertEqual(len(gaps), len([f for f in fr if f["dir"] == "rx"]) - 1)
        self.assertTrue(all(g["gap_s"] == 1.0 or g["gap_s"] == 2.0 for g in gaps))   # the tx reply is skipped


if __name__ == "__main__":
    unittest.main()
