"""End-to-end host rehearsal of the D1 standalone loop: RefLoop (the application's
reference state machine) against a fake standalone PL, through the real NotaryRelay and
the REAL signer (`sign_arm.sign_genome`, fixture key — the same key the fake PL verifies
with). Proves sequencing, refusals, the taxonomy and the run-log rules; proves nothing
about the PL RTL or the transport (as for L3's fake)."""

from __future__ import annotations

import copy
import os
import sys
import tempfile
import unittest
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R)); sys.path.insert(0, str(R / "host"))
from validators import nonce as nc  # noqa: E402
from validators import records  # noqa: E402
from validators import signer as sg  # noqa: E402
import l5_notary as n  # noqa: E402
import l5_refloop as rf  # noqa: E402
import p3_gate as g  # noqa: E402
import p3_genome as gn  # noqa: E402
import p3_oracle as po  # noqa: E402
import sign_arm  # noqa: E402

SEED = 0x9E3779B97F4A7C15
TOKEN = "5a" * 16


class FakeStandalonePL:
    """The PL + DEVCFG + DDR model for the standalone plane: MAC verify with the fixture
    key, xorshift nonce, functional sweep = the oracle over its own fabric, sticky fault."""

    def __init__(self, manifest, consts, holder, page_words):
        self.manifest, self.consts, self.holder = manifest, consts, holder
        self.page_words = page_words
        base, roles = g.gc.pinned_frames(manifest)
        self.fabric = {far: list(w) for far, w in base.items()}
        self.roles = roles
        self.nonce = SEED
        self.key_loaded = True
        self.fault = 0
        self.cfg_valid = False
        self.armed_done = False
        self.scores = [0] * 6
        self.hw_commit = [0] * 8
        self.readout = [0] * 12
        self.heartbeat = 0
        self.payload = [0] * 20
        self.tag_words = [0] * 4
        self.corrupt_staged = False
        self.tamper_after_write = None      # (far, word) to flip post-DMA

    # board plumbing
    def read_idcode(self):
        return 0x13722093

    def read_page(self):
        return list(self.page_words)

    def fclk0_hz(self):
        return 50_000_000

    def devcfg_healthy(self):
        return True

    def stage(self, streams):
        self.staged = [list(s) for s in streams]

    def reread(self):
        out = [list(s) for s in self.staged]
        if self.corrupt_staged:
            out[0][100] ^= 1
        return out

    def write(self):
        far_sets = {e["far_set"] for e in g.envelopes(self.manifest)}
        for words in self.staged:
            far, frames5 = g.parse_stream(words, far_sets)
            env = next(e for e in g.envelopes(self.manifest) if e["far_set"] == far)
            for k, f in enumerate(env["targets"]):
                self.fabric[f] = list(frames5[k])
            self.fabric[env["flush"]] = list(frames5[4])
        if self.tamper_after_write:
            far, w = self.tamper_after_write
            self.fabric[far][w] ^= 1 << 3
        return [{"int_sts": "0x00000004", "error_bits": []} for _ in self.staged]

    def readback_frame(self, far):
        return list(self.fabric[far])

    # AXI
    def axi_read(self, off):
        self.heartbeat += 7
        st = 1 << po.ST["alive"]
        if self.key_loaded:
            st |= 1 << po.ST["key_loaded"]
        if self.fault:
            st |= (1 << po.ST["fault"]) | (1 << po.ST["recovery_required"])
        if self.cfg_valid:
            st |= (1 << po.ST["cfg_valid_hw"]) | (1 << po.ST["tag_ok"]) | \
                  (1 << po.ST["sweep_done"]) | (1 << po.ST["tables_match"])
        if self.armed_done:
            st |= 1 << po.ST["scorer_done"]
        if off == po.STATUS:
            return st
        if off == po.FAULT:
            return self.fault
        if off == po.HEARTBEAT:
            return self.heartbeat
        if off == po.NONCE_LO:
            return self.nonce & 0xFFFFFFFF
        if off == po.NONCE_HI:
            return self.nonce >> 32
        if off in po.SCORES:
            return self.scores[po.SCORES.index(off)]
        if off in po.HW_COMMIT:
            return self.hw_commit[po.HW_COMMIT.index(off)]
        if off in po.READOUT:
            return self.readout[po.READOUT.index(off)]
        raise AssertionError(f"read of unmapped offset {off:#x}")

    def axi_write(self, off, val):
        if off in po.PAYLOAD:
            self.payload[po.PAYLOAD.index(off)] = val
            return
        if off in po.TAG:
            self.tag_words[po.TAG.index(off)] = val
            return
        if off == po.CTRL and val & po.ARM_STROBE:
            self._arm()
            return
        raise AssertionError(f"write of unmapped offset {off:#x}")

    def _arm(self):
        if self.fault:
            return                          # sticky: a faulted gate ignores further ARMs
        self.cfg_valid = False              # the latch clears on the next ARM attempt (L1)
        nonce_bytes = self.nonce.to_bytes(8, "little")
        self.nonce = nc.step(self.nonce)    # consumed by THIS attempt, whatever the outcome
        self.armed_done = True
        if not self.key_loaded:
            self.fault = po.F_ARM_NOKEY
            return
        commit = b"".join(w.to_bytes(4, "big") for w in self.payload[:8])
        tables = tuple((self.payload[8 + 2 * t] << 32) | self.payload[9 + 2 * t] for t in range(6))
        t0 = (self.tag_words[0] << 32) | self.tag_words[1]
        t1 = (self.tag_words[2] << 32) | self.tag_words[3]
        tag = t0.to_bytes(8, "little") + t1.to_bytes(8, "little")
        msg = sg.arm_message(commit, tables, nonce_bytes)
        if self.holder._sign(msg) != tag:
            self.fault = po.F_ARM_AUTH
            return
        actual = tuple(po.expected_tables(
            {f: self.fabric[f] for f, r in self.roles.items() if r == "target"}, self.consts))
        if actual != tables:
            self.fault = po.F_ARM_TABLE
            return
        self.cfg_valid = True
        self.scores = po.predict_scores(list(actual), self.consts)
        self.hw_commit = list(self.payload[:8])
        self.readout = [w for t in actual for w in ((t >> 32) & 0xFFFFFFFF, t & 0xFFFFFFFF)]


def private_key(tmp: Path) -> Path:
    p = tmp / "K.bin"
    p.write_bytes(bytes(range(16)))
    os.chmod(p, 0o600)
    return p


class RefLoopSession(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.holder = sg.KeyHolder(private_key(Path(cls.tmp.name)))
        cls.manifest = g.load_manifest()
        cls.consts = po.load_constants()
        blank = {f: list(w) for f, w in zip(
            *[iter([])] * 2)}  # placeholder, real blank below
        base, roles = g.gc.pinned_frames(cls.manifest)
        blank_frames = {f: list(base[f]) for f, r in roles.items() if r == "target"}
        cls.blank_commit = g.gate(g.build_streams(blank_frames, cls.manifest), cls.manifest)["candidate_sha256"]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def make(self, signer_fn=None):
        page = rf.build_identity_page(TOKEN, 0, 0x12345678, "9a" * 32, SEED, 0x900, 7, 3, 3)
        board = FakeStandalonePL(self.manifest, self.consts, self.holder, page)
        signer = signer_fn or (lambda req: sign_arm.sign_genome(self.holder, req["genome"], req["nonce"]))
        relay = n.NotaryRelay(TOKEN, signer, drop_budget=16, clock=lambda: 0.0)
        loop = rf.RefLoop(board, relay.handle_line, self.manifest, self.consts)
        return board, relay, loop

    def test_completed_session_validates_end_to_end(self):
        board, relay, loop = self.make()
        log = loop.run([gn.corpus_genome(2, self.manifest)])
        self.assertEqual(log["session_summary"]["epoch_end"]["kind"], "COMPLETED")
        log["notary_log"] = relay.notary_log()
        out = records.validate_standalone_run_log(log, self.blank_commit, SEED)
        self.assertEqual(out["scored"], 3)                  # opening, candidate, closing
        self.assertEqual(out["chain_length"], 4)            # + the closing unsigned control
        # the scores the fake PL produced are the oracle's own prediction (baseline check)
        first = log["loop_records"][0]["evidence"]["score"]["scores"]
        self.assertEqual(first, [18, 22, 20, 20, 20, 18])   # fabricmap base_restore train

    def test_gate_refusal_is_survived_and_logged(self):
        real = lambda req: sign_arm.sign_genome(self.holder, req["genome"], req["nonce"])  # noqa: E731

        def refusing(req):
            if req["seq"] == 2:
                return {"refused": {"finding_kinds": ["whitelist"]}}
            return real(req)
        board, relay, loop = self.make(refusing)
        log = loop.run([gn.corpus_genome(2, self.manifest)])
        log["notary_log"] = relay.notary_log()
        self.assertEqual(log["session_summary"]["epoch_end"]["kind"], "COMPLETED")
        self.assertEqual(log["loop_records"][1]["outcome"], "REFUSED_BY_GATE")
        records.validate_standalone_run_log(log, self.blank_commit, SEED)

    def test_link2_corruption_stops_before_any_dma(self):
        board, relay, loop = self.make()
        board.corrupt_staged = True
        log = loop.run([])
        s = log["session_summary"]
        self.assertEqual(s["epoch_end"]["kind"], "STOPPED")
        self.assertIn("LINK2", s["epoch_end"]["reason"])
        self.assertEqual(s["closing"]["baseline"], "not_reached")
        self.assertNotIn("closing_negative", log)

    def test_fabric_tamper_is_refused_by_the_pl_sweep(self):
        board, relay, loop = self.make()
        target = next(f for f, r in board.roles.items() if r == "target")
        # flip a whitelisted bit of the first target frame after every DMA
        far, w, b = gn.addresses(self.manifest)[0]
        board.tamper_after_write = (far, w)
        log = loop.run([])
        self.assertEqual(log["session_summary"]["epoch_end"]["kind"], "STOPPED")
        stopped = log["loop_records"][-1]
        # the tamper lands within the whitelist, so link 3 sees a different candidate
        self.assertIn(stopped["outcome"], ("STOP_LINK3", "REFUSED_BY_PL"))

    def test_identity_nonce_echo_mismatch_refuses_the_loop(self):
        board, relay, loop = self.make()
        board.nonce = nc.step(SEED)                          # PL was touched since the host looked
        log = loop.run([])
        self.assertEqual(log["session_summary"]["epoch_end"]["kind"], "STOPPED")
        self.assertIn("identity", log["session_summary"]["epoch_end"]["reason"])
        self.assertTrue(log["app_identity"]["findings"])
        self.assertEqual(log["loop_records"], [])

    def test_closing_unsigned_control_is_the_last_operation_and_refused(self):
        board, relay, loop = self.make()
        log = loop.run([])
        neg = log["closing_negative"]
        self.assertEqual(neg["fault"], po.F_ARM_AUTH)
        self.assertEqual(int(neg["nonce_after"], 16), nc.step(int(neg["nonce_before"], 16)))
        # after the sticky fault, the PL is done: this really was the last device operation
        self.assertEqual(board.fault, po.F_ARM_AUTH)


if __name__ == "__main__":
    unittest.main()
