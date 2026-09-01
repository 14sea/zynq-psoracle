"""host/l5_runner.py — the L5 board runner's host-side behaviour.

The runner is thin by design (on this rung the loop lives in the firmware), so what is
worth testing is exactly what it does own: reading framed lines out of a byte stream that
also carries console noise, answering a sign request with a reply the APPLICATION can
parse, attaching the audit request before that reply, spotting a U-Boot banner as a crash,
and refusing to start against an image that is not the pinned one.

The frames fed in here are produced by the C wire twin, so this is the runner reading the
bytes the board will actually send (see tests/test_firmware_wire_contract.py)."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R)); sys.path.insert(0, str(R / "host")); sys.path.insert(0, str(R / "scripts"))
import l5_notary as n  # noqa: E402
import l5_runner as lr  # noqa: E402

TOKEN = "5a" * 16
TWIN = R / "firmware" / "build" / "p3_wire_twin"


def twin(*commands: str) -> list[str]:
    subprocess.run(["make", "wire"], cwd=R / "firmware", check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    out = subprocess.run([str(TWIN)], input="\n".join(commands) + "\n",
                         capture_output=True, text=True, check=True).stdout
    return [ln for ln in out.splitlines() if ln.strip()]


class FakeTransport:
    """Feeds canned bytes out and records what the runner writes back."""

    def __init__(self, chunks: list[bytes]):
        self.chunks = list(chunks)
        self.written: list[str] = []

        class _S:
            def __init__(self, outer):
                self.outer = outer

            def write(self, data):
                self.outer.written.append(data.decode())

        self._serial = _S(self)

    def drain(self) -> bytes:
        return self.chunks.pop(0) if self.chunks else b""


class Reader(unittest.TestCase):
    def test_frames_are_recovered_from_a_split_byte_stream(self):
        line, = twin(f"hb token={TOKEN} seq=7")
        raw = (line + "\n").encode()
        t = FakeTransport([raw[:9], raw[9:]])       # split mid-frame, as a UART would
        r = lr.LineReader(t)
        self.assertEqual(r.poll(), [])              # a partial line is not yet a line
        self.assertEqual(r.poll(), [line])

    def test_console_noise_is_kept_but_not_mistaken_for_a_frame(self):
        line, = twin(f"hb token={TOKEN} seq=1")
        t = FakeTransport([b"Uncompressing kernel...\n" + (line + "\n").encode()])
        got = lr.LineReader(t).poll()
        self.assertEqual(len(got), 2)
        self.assertFalse(got[0].startswith(n.MAGIC))
        self.assertTrue(got[1].startswith(n.MAGIC))

    def test_a_uboot_banner_is_a_crash_signal(self):
        t = FakeTransport([b"\n\nU-Boot 2018.01 (Jan 01 2018)\nzynq-uboot> "])
        r = lr.LineReader(t)
        r.poll()
        self.assertTrue(r.saw_uboot_banner())
        collector = n.Collector(TOKEN, heartbeat_s=10, clock=lambda: 0.0)
        collector.on_banner()
        self.assertEqual(collector.epoch_end["kind"], "CRASHED")

    def test_replies_are_newline_terminated_for_the_application(self):
        """p3_app.c recv_line() breaks on '\\n' and SKIPS '\\r': a '\\r'-terminated reply
        would hang the application forever."""
        t = FakeTransport([])
        lr.send_raw_line(t, "P3L5 SIGNOK 1 " + TOKEN + " - 00000000")
        self.assertTrue(t.written[0].endswith("\n"))
        self.assertFalse(t.written[0].rstrip("\n").endswith("\r"))


class Verdict(unittest.TestCase):
    """A non-consumed ARM must never be reported as a pass. Session 1 ended exactly this
    way, so the mapping is tested rather than trusted."""

    def test_only_a_completed_epoch_is_a_pass(self):
        self.assertEqual(lr.outcome_for({"kind": "COMPLETED", "reason": "budget"}), "PASS")

    def test_a_stopped_epoch_is_a_hold_and_carries_its_reason(self):
        v = lr.outcome_for({"kind": "STOPPED",
                            "reason": "the nonce did not step: the PL did not consume this ARM"})
        self.assertTrue(v.startswith("HOLD STOPPED"))
        self.assertIn("did not consume", v)
        self.assertNotIn("PASS", v)

    def test_protocol_and_crashed_are_holds_too(self):
        for kind in ("PROTOCOL", "CRASHED"):
            v = lr.outcome_for({"kind": kind, "reason": "x"})
            self.assertTrue(v.startswith(f"HOLD {kind}"))
            self.assertNotEqual(v, "PASS")


class RejectionClassification(unittest.TestCase):
    """Session 3 (2026-09-01) printed `KILL run_log rejected: …` for a counter the firmware
    got wrong. The owner ruled: KILL only for a preregistration §3 item; schema /
    accounting / instrument defects are HOLD. Tested in both directions."""

    def test_an_accounting_rejection_is_a_hold(self):
        from validators import records
        v = lr.classify_rejection(records.RecordError("audit must report audited <= total (rule ix)"))
        self.assertTrue(v.startswith("HOLD instrument:"), v)
        self.assertNotIn("KILL", v)

    def test_a_falsifier_is_a_kill(self):
        from validators import records
        v = lr.classify_rejection(records.Falsified("(viii) the closing unsigned ARM was not refused F_ARM_AUTH"))
        self.assertTrue(v.startswith("KILL falsified:"), v)

    def test_session_3s_own_log_now_classifies_as_hold(self):
        """The recorded evidence, read-only, through the current validator: whatever the
        current rejection reason is, it must not be a Falsified one."""
        import json
        from validators import records
        import p3_gate as g
        import p3_genome as gn
        log = json.loads((R / "evidence/l5_17A6_2026-09-01-03/run_log.json").read_text())
        phen = g.load_manifest()
        blank = g.gate(g.build_streams(gn.frames_from_genome(gn.blank_genome(phen), phen), phen),
                       phen)["candidate_sha256"]
        seed = int(json.loads((R / "manifests/l5_manifest.json").read_text())["carrier"]["nonce_seed"], 16)
        with self.assertRaises(records.RecordError) as cm:
            records.validate_standalone_run_log(log, blank, seed)
        self.assertNotIsInstance(cm.exception, records.Falsified)
        self.assertTrue(lr.classify_rejection(cm.exception).startswith("HOLD instrument:"))

    def test_the_runner_source_no_longer_maps_every_rejection_to_kill(self):
        src = (R / "host/l5_runner.py").read_text()
        self.assertNotIn('f"KILL run_log rejected', src)
        self.assertIn("classify_rejection(exc)", src)


class ImagePinning(unittest.TestCase):
    """The refusal must be REACHED and be ABOUT the image — a run that stops earlier (a
    missing ruling, say) would also return 2 and would prove nothing."""

    def _args(self, tmp: Path, image: Path) -> list[str]:
        import json
        import time
        (tmp / "ruling.json").write_text(json.dumps(
            {"ruling": lr.RULING_TEXT, "boardid": "17A6", "granted_by": "14sea",
             "date": "2026-08-31-99"}))
        (tmp / "boundary.json").write_text(json.dumps(
            {"schema": "principal_boundary", "schema_version": "1.0.0",
             "runner_user": "test", "signer_user": "p3signer", "pod_group": "p3jtag",
             "key_store": "/var/lib/p3signer/keys", "all_passed": True,
             "checks": [{"check": c, "passed": True, "detail": "fixture"} for c in
                        ("R1_runner_is_not_signer", "R2_runner_cannot_read_key",
                         "R3_runner_cannot_open_pod", "R4_signer_reachable_and_holds_key",
                         "R5_signer_in_pod_group")],
             "at": time.time()}))
        return ["--ruling", str(tmp / "ruling.json"), "--boundary", str(tmp / "boundary.json"),
                "--out", str(tmp / "out"), "--manifest", str(R / "builds/p3/carrier_manifest.json"),
                "--bitstream", str(R / "builds/p3/p3.bit"), "--image", str(image)]

    def test_an_unpinned_image_is_refused_before_any_board_contact(self):
        import contextlib
        import io
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "img.bin").write_bytes(b"not the pinned image")
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                rc = lr.main(self._args(tmp, tmp / "img.bin"))
            self.assertEqual(rc, 2)      # REFUSED, never 0/1 (which mean a session ran)
            self.assertIn("not the pinned one", err.getvalue(),
                          f"refused for the wrong reason: {err.getvalue().strip()}")
            self.assertFalse((tmp / "out").exists(), "no evidence dir before the checks pass")


if __name__ == "__main__":
    unittest.main()
