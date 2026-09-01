"""host/l6_reader.py — the non-blocking console reader (C1 #1 finding 2).

Driven with a fake serial handle whose bytes arrive in scripted reads at scripted times,
so the properties the owner asked for are each a test: lines that arrive at different
times get different stamps; lines completed by one OS read honestly share one; a line
split across polls is completed with the later read's stamp and the raw bytes stay
verbatim; a U-Boot banner is still the crash signal; `drain()` is never called (the fake
has none, so a call would raise); and the runner's console loop uses this reader."""
from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R / "host"))
import l6_reader as lrd  # noqa: E402

TOKEN = "ab" * 16


class FakeSerial:
    """`chunks` = list of byte strings; each poll that finds one waiting returns it whole."""

    def __init__(self, chunks: list[bytes]):
        self.chunks = list(chunks)
        self.reads = 0

    @property
    def in_waiting(self) -> int:
        return len(self.chunks[0]) if self.chunks else 0

    def read(self, n: int) -> bytes:
        self.reads += 1
        c = self.chunks.pop(0)
        assert n == len(c)
        return c


class Clock:
    def __init__(self):
        self.t = 100.0

    def mono(self):
        return self.t

    def wall(self):
        return self.t + 1e9


def reader(chunks):
    clk = Clock()
    return lrd.L6LineReader(FakeSerial(chunks), clock_mono=clk.mono, clock_wall=clk.wall), clk


class Stamps(unittest.TestCase):
    def test_lines_arriving_at_different_times_get_different_stamps(self):
        r, clk = reader([b"P3L5 HB 1 x -\n", b"P3L5 HB 1 y -\n", b"P3L5 REC 1 z -\n"])
        stamps = []
        for _ in range(3):
            got = r.poll()
            self.assertEqual(len(got), 1)
            stamps.append(got[0][1])
            clk.t += 0.02                       # the runner's ~20 ms poll
        self.assertEqual(len(set(stamps)), 3)
        for got, want in zip(stamps, (100.0, 100.02, 100.04)):
            self.assertAlmostEqual(got, want)

    def test_lines_completed_by_one_read_share_its_stamp(self):
        r, clk = reader([b"P3L5 HB 1 a -\nP3L5 HB 1 b -\nP3L5 AUDIT 1 c -\n"])
        got = r.poll()
        self.assertEqual([g[0] for g in got], ["P3L5 HB 1 a -", "P3L5 HB 1 b -", "P3L5 AUDIT 1 c -"])
        self.assertEqual({g[1] for g in got}, {100.0})
        self.assertEqual({g[2] for g in got}, {100.0 + 1e9})

    def test_a_half_line_across_polls_is_completed_with_the_later_stamp(self):
        r, clk = reader([b"P3L5 SIGN", b"REQ 2 t p 0\nP3L5 H"])
        self.assertEqual(r.poll(), [])          # a partial line is not yet a line …
        self.assertEqual(r.buf, b"P3L5 SIGN")   # … but its bytes are kept
        clk.t += 0.02
        got = r.poll()
        self.assertEqual(got, [("P3L5 SIGNREQ 2 t p 0", 100.02, 100.02 + 1e9)])
        self.assertEqual(r.buf, b"P3L5 H")
        self.assertEqual(bytes(r.raw), b"P3L5 SIGNREQ 2 t p 0\nP3L5 H")

    def test_raw_bytes_are_verbatim_including_cr_and_noise(self):
        payload = b"## Starting application at 0x02000000 ...\r\nP3L5 HB 3 q -\r\n\xff\xfe junk\n"
        r, _ = reader([payload])
        got = r.poll()
        self.assertEqual(bytes(r.raw), payload)
        self.assertEqual([g[0] for g in got][:2], ["## Starting application at 0x02000000 ...", "P3L5 HB 3 q -"])

    def test_a_uboot_banner_is_still_the_crash_signal(self):
        r, _ = reader([b"\n\nU-Boot 2018.01 (Jan 01 2018)\nzynq-uboot> "])
        r.poll()
        self.assertTrue(r.saw_uboot_banner())

    def test_nothing_waiting_returns_immediately_and_reads_nothing(self):
        r, _ = reader([])
        self.assertEqual(r.poll(), [])
        self.assertEqual(r.reads, 0)

    def test_drain_is_never_called(self):
        """FakeSerial has no drain(); the reader touched only in_waiting and read(). The
        source check looks for a CALL, not the word — the docstring names drain() to say
        why this module exists."""
        src = inspect.getsource(lrd)
        self.assertNotIn("ser.drain(", src); self.assertNotIn("self.drain(", src)
        self.assertEqual(src.count("in_waiting"), 1 + src.count("`read(in_waiting)`"))  # the one real read path
        r, _ = reader([b"P3L5 HB 1 a -\n"])
        r.poll()
        self.assertEqual(r.ser.reads, 1)


class RunnerWiring(unittest.TestCase):
    def test_the_runner_console_loop_uses_the_l6_reader_on_the_same_handle(self):
        import l6_runner as l6
        src = inspect.getsource(l6.run_l6)
        loop = src[src.index("the console belongs to the application"):src.index("assemble, adjudicate")]
        self.assertIn("lrd.L6LineReader(session.transport._serial)", loop)
        self.assertNotIn("l5.LineReader", loop)
        self.assertNotIn(".drain(", loop)            # a call, not the comment that names it
        self.assertNotIn("transport.drain", src)
        # each line carries its own stamp into the timeline; no batch stamp
        self.assertIn("for line, t_mono, t_wall in reader.poll():", loop)
        self.assertNotIn("t_mono, t_wall = time.monotonic(), time.time()", loop)


if __name__ == "__main__":
    unittest.main()
