"""L3 runner against a fake P3 board (the console/devcfg fake from zynq-psmap's S0b tests,
extended with a fabric that PCAP writes and reads, and the P3 PL modelled on the host).

What the fake proves: the runner's sequencing and its STOPs — link 2 halts before any DMA,
link 3 halts before any ARM, a PL refusal yields no score_record, the AXI allowlist refuses
host-side, the run log validator rejects a forged score. What it cannot prove: the PL
itself (that is `sim/run_all.sh` on the RTL) and the transport (psmap's board runs).
The fake's PL uses the same `p3_oracle` predictor as the runner for its scores, so the
score comparison here is a plumbing check, not an independent scorer model.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts")); sys.path.insert(0, str(REPO / "host")); sys.path.insert(0, str(REPO / "tests")); sys.path.insert(0, str(REPO))
import board_session as bsn  # noqa: E402
import pcap_probe_plan as pp  # noqa: E402
import l3_runner as l3  # noqa: E402
import p3_gate as g  # noqa: E402
import p3_oracle as po  # noqa: E402
from validators import signer as sg, nonce as nn, records  # noqa: E402
from test_s0b_runner import FakeUBoot, FakeTransport, PROMPT  # noqa: E402

DUMMY = REPO / "builds/p3"
MANIFEST = json.load(open(DUMMY / "carrier_manifest.json"))
PHEN = g.load_manifest()
CONSTS = po.load_constants()
TABLE = l3.load_p3_table(DUMMY / "p3.bit", MANIFEST)
FAR_SETS = {e["far_set"] for e in g.envelopes(PHEN)}
KA = json.load(open(REPO / "imported/fabricmap/gate_runs/claimb_round1_known_answer_2026_08_14/known_answer.json"))


class FakeP3Board(FakeUBoot):
    """devcfg write DMA applies envelopes to `fabric`; readback DMA reads from it; the AXI
    window is the L1 register file with the gate modelled on a fixture KeyHolder."""

    def __init__(self, key_path: Path, **kw):
        super().__init__(deliver=lambda far: [0] * 101 + self.fabric[far], **kw)
        self.fabric = {far: list(w) for far, w in TABLE["frames"].items()}
        self.reported_size = (DUMMY / "p3.bit").stat().st_size
        self.holder = None                      # unprovisioned after configuration
        self.key_loaded = False
        self.nonce = int(MANIFEST["nonce_seed"], 16)
        self.staging = [0] * 24
        self.fault, self.cfg_valid, self.armed, self.done = 0, 0, 0, 0
        self.hw_commit, self.readout, self.scores = [0] * 8, [0] * 6, [0] * 6
        self.heartbeat = 1000
        self.write_dmas, self.arm_attempts = 0, 0
        self.drop_write = False          # the write DMA "completes" but the fabric is untouched
        self.tamper_word = None          # (index, xor) applied to the staged DDR word

    # ---- the signer's JTAG mem-AP path (never the console): four write-once words + commit
    def provision(self, key_path: Path):
        if self.key_loaded:
            raise AssertionError("key register is write-once: a second provisioning is SLVERR on the AHB")
        self.holder = sg.KeyHolder(key_path); self.key_loaded = True

    # ---- devcfg
    def queue_dma(self, src, dst, src_len, dst_len):
        if src == l3.WR_BUF | pp.DMA_HOLD_TAG and dst == pp.PCAP_ENDPOINT:
            self.write_dmas += 1
            words = [self.mem.get(l3.WR_BUF + 4 * i, 0) for i in range(src_len)]
            far, frames = g.parse_stream(words, FAR_SETS)
            env = next(e for e in g.envelopes(PHEN) if e["far_set"] == far)
            if not self.drop_write:
                for k, f in enumerate(env["targets"]):
                    self.fabric[f] = list(frames[k])
                self.fabric[env["flush"]] = list(frames[4])
        super().queue_dma(src, dst, src_len, dst_len)

    # ---- AXI
    def status(self):
        busy = 0
        return (busy | (1 if self.fault else 0) << 1 | self.cfg_valid << 2 | self.done << 4 | self.armed << 5
                | (1 if self.hw_commit != [0] * 8 else 0) << 6 | (1 if self.fault else 0) << 7 | 1 << 8
                | self.done << 9 | self.cfg_valid << 10 | (1 if self.key_loaded else 0) << 11)

    def word(self, addr):
        if po.AXI_BASE <= addr < po.AXI_BASE + 0x10000:
            off = addr - po.AXI_BASE
            if off == po.STATUS: return self.status()
            if off == po.FAULT: return self.fault
            if off in po.SCORES: return self.scores[po.SCORES.index(off)]
            if off == po.HEARTBEAT: self.heartbeat += 7; return self.heartbeat
            if off == po.NONCE_LO: return self.nonce & 0xFFFFFFFF
            if off == po.NONCE_HI: return self.nonce >> 32
            if off in po.HW_COMMIT: return self.hw_commit[po.HW_COMMIT.index(off)]
            if off in po.READOUT:
                j = po.READOUT.index(off); t = self.readout[j >> 1]
                return (t >> 32) & 0xFFFFFFFF if j % 2 == 0 else t & 0xFFFFFFFF
            raise AssertionError(f"SLVERR read at {off:#x}: a data abort, the board would reset")
        return super().word(addr)

    def reply(self, line: str) -> bytes:
        parts = line.split()
        if parts[0] == "mw.l":
            addr, value = int(parts[1], 16), int(parts[2], 16)
            if po.AXI_BASE <= addr < po.AXI_BASE + 0x10000:
                self.sent.append(line)
                off = addr - po.AXI_BASE
                if off in po.PAYLOAD: self.staging[po.PAYLOAD.index(off)] = value
                elif off in po.TAG: self.staging[20 + po.TAG.index(off)] = value
                elif off == po.CTRL:
                    if value & po.ARM_STROBE: self.arm(bool(value & po.MODE_HOLDOUT))
                else: raise AssertionError(f"SLVERR write at {off:#x}")
                return line.encode() + b"\r\n" + self.prompt
            if l3.WR_BUF <= addr < l3.WR_BUF + 4 * l3.STREAM_WORDS and self.tamper_word:
                i, x = self.tamper_word
                if addr == l3.WR_BUF + 4 * i:
                    line = f"mw.l {addr:#010x} {value ^ x:#010x} 1"     # DDR holds something else
        return super().reply(line)

    def arm(self, holdout):
        self.arm_attempts += 1
        if self.fault: return                      # refused; nonce not consumed
        if not self.key_loaded:
            self.nonce = nn.step(self.nonce); self.fault = po.F_ARM_NOKEY; return
        w = self.staging
        commit = b"".join(x.to_bytes(4, "big") for x in w[:8])
        tables = [(w[8 + 2 * t] << 32) | w[9 + 2 * t] for t in range(6)]
        t0, t1 = (w[20] << 32) | w[21], (w[22] << 32) | w[23]
        tag = t0.to_bytes(8, "little") + t1.to_bytes(8, "little")
        ok = self.holder._sign(sg.arm_message(commit, tables, self.nonce.to_bytes(8, "little"))) == tag
        self.nonce = nn.step(self.nonce)
        self.cfg_valid = self.armed = 0
        if not ok: self.fault = po.F_ARM_AUTH; return
        self.hw_commit = list(w[:8])
        self.readout = po.expected_tables({f: self.fabric[f] for f in map(lambda h: int(h, 16), MANIFEST["target_fars"])}, CONSTS)
        if self.readout != tables: self.fault = po.F_ARM_TABLE; return
        self.cfg_valid = self.armed = self.done = 1
        self.scores = po.predict_scores(self.readout, CONSTS, holdout)


class FixtureSigner(l3.SubprocessSigner):
    """The real sign_arm.py for signing; provisioning modelled as the JTAG mem-AP write into the
    fake PL (a path the console — and so the runner — never has)."""
    def __init__(self, key_path, board):
        super().__init__(key_path); self.board = board; self.provisions = []
    def provision(self, execute=False, ruling=None, alt_key_path=None):
        kp = alt_key_path or self.key_path
        self.provisions.append(str(kp))
        self.board.provision(kp)
        self.key_id = sg.KeyHolder(kp).key_id
        return {"executed": True, "modelled": "jtag-mem-ap"}


class Harness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); root = Path(self.tmp.name)
        self.key = root / "K.bin"; self.key.write_bytes(bytes(range(16))); os.chmod(self.key, 0o400)
        self.other_key = root / "K2.bin"; self.other_key.write_bytes(bytes(range(16, 32))); os.chmod(self.other_key, 0o400)
        self.out = root / "evidence"; self.out.mkdir()
        self.ruling = {"ruling": l3.RULING_TEXT, "boardid": "17A6", "date": "fixture"}

    def tearDown(self):
        self.tmp.cleanup()

    def run_chain(self, board: FakeP3Board, key=None, holdout=False, candidate=None, negative=None):
        session = bsn.BoardSession(FakeTransport(board))
        cfg = {"manifest": MANIFEST, "bitstream": DUMMY / "p3.bit", "candidate": candidate or g.known_answer_candidate(PHEN),
               "signer": FixtureSigner(key or self.key, board), "holdout": holdout, "consts": CONSTS, "table": TABLE,
               "negative": negative, "wrong_key_path": self.other_key}
        summary = l3.run_l3(session, self.out, self.ruling, cfg)
        log = json.load(open(self.out / "run_log.json"))
        return summary, log, board


class Chain(Harness):
    def test_known_answer_passes_end_to_end(self):
        s, log, b = self.run_chain(FakeP3Board(self.key))
        self.assertEqual(s["outcome"], "PASS", s["outcome"])
        kinds = [r["schema"] for r in log["records"]]
        self.assertEqual(kinds, ["candidate", "gate_verdict", "oracle_record", "arm_record", "score_record"])
        score = log["records"][-1]
        self.assertEqual(score["scores"], KA["scores"]["candidate"]["train"])
        self.assertEqual(score["hw_candidate_commit"], log["records"][1]["candidate_sha256"])
        self.assertTrue(score["configuration_valid_hw"])
        self.assertEqual(b.write_dmas, 3)
        self.assertEqual(b.arm_attempts, 1)
        self.assertIsInstance(s["run_log_validation"], dict)
        self.assertEqual(len(s["run_log_validation"]), 1)
        self.assertGreater(score["heartbeat"]["after"], score["heartbeat"]["before"])
        self.assertEqual(log["records"][2]["readback_sha256"], log["records"][1]["candidate_sha256"])
        self.assertEqual(len(list(self.out.glob("L3_read_*.json"))), 12)

    def test_holdout_mode_scores_the_holdout_slice(self):
        s, log, b = self.run_chain(FakeP3Board(self.key), holdout=True)
        self.assertEqual(s["outcome"], "PASS")
        self.assertEqual(log["records"][-1]["scores"], KA["scores"]["candidate"]["holdout"])

    def test_link2_mismatch_stops_before_any_dma(self):
        b = FakeP3Board(self.key); b.tamper_word = (23 + 51, 0x8000)     # word 51 of the first target frame
        s, log, b = self.run_chain(b)
        self.assertTrue(s["outcome"].startswith(f"STOP {l3.STOP_LINK2}"), s["outcome"])
        self.assertEqual(b.write_dmas, 0); self.assertEqual(b.arm_attempts, 0)
        self.assertEqual([r["schema"] for r in log["records"]], ["candidate", "gate_verdict"])

    def test_link3_mismatch_stops_before_any_arm(self):
        b = FakeP3Board(self.key); b.drop_write = True
        s, log, b = self.run_chain(b)
        self.assertTrue(s["outcome"].startswith(f"STOP {l3.STOP_LINK3}"), s["outcome"])
        self.assertEqual(b.write_dmas, 3); self.assertEqual(b.arm_attempts, 0)
        self.assertNotIn("arm_record", [r["schema"] for r in log["records"]])
        self.assertTrue(s["outcome"].split(":")[1].strip().startswith("0x00400a20"))

    def test_wrong_signer_key_is_refused_by_the_pl_and_yields_no_score(self):
        board = FakeP3Board(self.key)
        class Mismatch(FixtureSigner):
            def provision(self, execute=False, ruling=None, alt_key_path=None):
                return super().provision(execute, ruling, alt_key_path or Path(self.key_path).with_name("K.bin"))
        session = bsn.BoardSession(FakeTransport(board))
        cfg = {"manifest": MANIFEST, "bitstream": DUMMY / "p3.bit", "candidate": g.known_answer_candidate(PHEN),
               "signer": Mismatch(self.other_key, board), "holdout": False, "consts": CONSTS, "table": TABLE, "negative": None}
        s = l3.run_l3(session, self.out, self.ruling, cfg); log = json.load(open(self.out / "run_log.json")); b = board
        self.assertTrue(s["outcome"].startswith(f"STOP {l3.STOP_ARM}"), s["outcome"])
        self.assertEqual(b.arm_attempts, 1); self.assertEqual(b.fault, po.F_ARM_AUTH)
        arm = log["records"][-1]; self.assertEqual(arm["schema"], "arm_record")
        self.assertEqual(arm["pl_refusal"]["name"], "F_ARM_AUTH")
        self.assertNotIn("score_record", [r["schema"] for r in log["records"]])
        self.assertNotEqual(arm["axi_after"]["nonce"], arm["nonce"], "the nonce is consumed by a refused ARM")

    def test_a_forged_score_is_rejected_by_the_run_log_validator(self):
        s, log, b = self.run_chain(FakeP3Board(self.key), negative="unsigned")
        arm = next(r for r in log["records"] if r["schema"] == "arm_record")
        forged = {"schema": "score_record", "schema_version": "1.0.0", "arm_record_sha256": records.canonical_sha256(arm),
                  "configuration_valid_hw": True, "hw_candidate_commit": arm["candidate_commit"],
                  "functional_readout": arm["expected_tables"], "scores": [40] * 6, "host_prediction": [40] * 6}
        log["records"].append(forged)
        # rule (v) with the truthful latch value; the forged 'true' passes (i)-(v) only because the
        # forger also lied about the latch — that is exactly the line's residual, which is why
        # the PL's own HW_COMMIT/latch are the authority, not this validator
        forged["configuration_valid_hw"] = False
        with self.assertRaises(records.RecordError) as cm:
            records.validate_run_log(log)
        self.assertIn("(v)", str(cm.exception))

    def test_gate_refusal_never_reaches_the_board(self):
        cand = g.known_answer_candidate(PHEN); cand[0x00400A20] = list(cand[0x00400A20]); cand[0x00400A20][3] ^= 1
        s, log, b = self.run_chain(FakeP3Board(self.key), candidate=cand)
        self.assertTrue(s["outcome"].startswith("STOP GATE_REFUSED"))
        self.assertEqual(b.sent, [])

    def test_bitstream_not_the_manifests_is_refused(self):
        with self.assertRaises(bsn.SessionRefusal):
            l3.load_p3_table(l3.pr.CARRIER_BIT, MANIFEST)


class NegativeControls(Harness):
    def check(self, kind, fault):
        s, log, b = self.run_chain(FakeP3Board(self.key), negative=kind)
        self.assertEqual(s["outcome"], "PASS", s["outcome"])
        neg = log["records"][-1]
        self.assertEqual(neg["schema"], "negative_control"); self.assertEqual(neg["kind"], kind)
        self.assertEqual(neg["fault"], fault); self.assertFalse(neg["configuration_valid_hw"]); self.assertFalse(neg["scored"])
        self.assertTrue(neg["refused_as_expected"]); self.assertNotEqual(neg["nonce"], neg["nonce_after"])
        self.assertEqual(b.arm_attempts, 2)
        self.assertEqual(b.fault, fault)
        self.assertIsInstance(s["run_log_validation"], dict)

    def test_unsigned(self): self.check("unsigned", po.F_ARM_AUTH)
    def test_replay(self): self.check("replay", po.F_ARM_AUTH)
    def test_other_candidate(self): self.check("other_candidate", po.F_ARM_AUTH)
    def test_wrong_table(self): self.check("wrong_table", po.F_ARM_TABLE)

    def test_unprovisioned_is_a_pre_control_with_no_provisioning_and_no_score(self):
        s, log, b = self.run_chain(FakeP3Board(self.key), negative="unprovisioned")
        self.assertEqual(s["outcome"], "PASS", s["outcome"])
        self.assertFalse(b.key_loaded); self.assertEqual(b.fault, po.F_ARM_NOKEY)
        self.assertFalse(s["key_loaded_observed"])
        kinds = [r["schema"] for r in log["records"]]
        self.assertNotIn("score_record", kinds); self.assertEqual(kinds[-1], "negative_control")
        neg = log["records"][-1]; self.assertEqual(neg["fault"], 12); self.assertTrue(neg["refused_as_expected"])
        arm = log["records"][-2]; self.assertFalse(arm["key_loaded_observed"])

    def test_wrong_key_is_a_pre_control(self):
        s, log, b = self.run_chain(FakeP3Board(self.key), negative="wrong_key")
        self.assertEqual(s["outcome"], "PASS", s["outcome"])
        self.assertEqual(b.fault, po.F_ARM_AUTH)
        self.assertEqual(log["records"][-1]["kind"], "wrong_key")
        self.assertNotIn("score_record", [r["schema"] for r in log["records"]])

    def test_key_not_loaded_after_provisioning_stops_before_any_arm(self):
        board = FakeP3Board(self.key)
        class Silent(FixtureSigner):
            def provision(self, execute=False, ruling=None, alt_key_path=None): return {"executed": False}
        session = bsn.BoardSession(FakeTransport(board))
        cfg = {"manifest": MANIFEST, "bitstream": DUMMY / "p3.bit", "candidate": g.known_answer_candidate(PHEN),
               "signer": Silent(self.key, board), "holdout": False, "consts": CONSTS, "table": TABLE, "negative": None}
        s = l3.run_l3(session, self.out, self.ruling, cfg)
        self.assertTrue(s["outcome"].startswith("STOP KEY_NOT_LOADED"), s["outcome"]); self.assertEqual(board.arm_attempts, 0)

    def test_runner_never_writes_or_reads_the_key_register(self):
        s, log, b = self.run_chain(FakeP3Board(self.key))
        self.assertEqual(s["outcome"], "PASS")
        for line in b.sent:
            for off in po.KEY:
                self.assertNotIn(f"{po.axi(off):#010x}", line)
        self.assertTrue(po.READABLE.isdisjoint(po.KEY) and po.WRITABLE.isdisjoint(po.KEY))

    def test_a_pl_that_accepts_an_unsigned_arm_is_a_kill(self):
        class Broken(FakeP3Board):
            def arm(self, holdout):
                self.arm_attempts += 1; self.nonce = nn.step(self.nonce); self.key_loaded = True
                self.hw_commit = list(self.staging[:8]); self.cfg_valid = self.armed = self.done = 1
                self.scores = po.predict_scores(po.expected_tables({int(h, 16): self.fabric[int(h, 16)] for h in MANIFEST["target_fars"]}, CONSTS), CONSTS)
        s, log, b = self.run_chain(Broken(self.key), negative="unsigned")
        self.assertTrue(s["outcome"].startswith("KILL"), s["outcome"])
        self.assertNotIn("negative_control", [r["schema"] for r in log["records"]])

    def test_validator_rejects_a_negative_control_that_validated(self):
        with self.assertRaises(records.RecordError):
            records.validate({"schema": "negative_control", "schema_version": "1.0.0", "kind": "unsigned",
                              "arm_record_sha256": "0" * 64, "nonce": "0" * 16, "configuration_valid_hw": True,
                              "fault": 0, "scored": False, "refused_as_expected": False})


class LiveSignerRehearsal(unittest.TestCase):
    """Fake board, REAL signer principal: signing crosses the sudo boundary to p3signer
    (provisioning is modelled, the JTAG path being a board action). Skipped where the
    principal does not exist."""
    def test_known_answer_through_the_real_signer(self):
        import pwd
        try: pwd.getpwnam("p3signer")
        except KeyError: self.skipTest("no p3signer principal on this host")
        key = Path("/var/lib/p3signer/keys/K.bin")
        with tempfile.TemporaryDirectory() as d:
            board = FakeP3Board(REPO / "tests" / "__nokey__")  # placeholder; provision below sets the holder
            class RealSign(l3.SubprocessSigner):
                def provision(self, execute=False, ruling=None, alt_key_path=None):
                    # the fake PL must verify with the SAME K the real signer holds: obtain nothing
                    # from the runner's side — instead ask the signer to sign a probe and model the PL
                    # as "accepting the signer's tags" by delegating verification to the signer process.
                    board.key_loaded = True; board.verify_via_signer = self; return {"executed": True, "modelled": "jtag-mem-ap"}
            signer = RealSign(key, signer_user="p3signer")
            def arm_with_signer(holdout):
                board.arm_attempts += 1
                if board.fault: return
                w = board.staging
                commit = b"".join(x.to_bytes(4, "big") for x in w[:8]); tables = [(w[8 + 2 * t] << 32) | w[9 + 2 * t] for t in range(6)]
                t0, t1 = (w[20] << 32) | w[21], (w[22] << 32) | w[23]
                tag = t0.to_bytes(8, "little") + t1.to_bytes(8, "little")
                nonce = board.nonce.to_bytes(8, "little")
                # PL verification modelled by re-signing through the real principal and comparing tags
                ref = signer.sign({"writable": True, "candidate_sha256": commit.hex()}, commit, tables, nonce)
                board.nonce = nn.step(board.nonce); board.cfg_valid = board.armed = 0
                if ref.tag != tag: board.fault = po.F_ARM_AUTH; return
                board.hw_commit = list(w[:8])
                board.readout = po.expected_tables({int(h, 16): board.fabric[int(h, 16)] for h in MANIFEST["target_fars"]}, CONSTS)
                if board.readout != tables: board.fault = po.F_ARM_TABLE; return
                board.cfg_valid = board.armed = board.done = 1; board.scores = po.predict_scores(board.readout, CONSTS, holdout)
            board.arm = arm_with_signer
            session = bsn.BoardSession(FakeTransport(board))
            cfg = {"manifest": MANIFEST, "bitstream": DUMMY / "p3.bit", "candidate": g.known_answer_candidate(PHEN),
                   "signer": signer, "holdout": False, "consts": CONSTS, "table": TABLE, "negative": None}
            s = l3.run_l3(session, Path(d), {"ruling": l3.RULING_TEXT}, cfg)
            self.assertEqual(s["outcome"], "PASS", s["outcome"])
            self.assertEqual(signer.key_id[:8], "b4c022a2")


class Allowlist(unittest.TestCase):
    def test_axi_reads_and_writes_outside_the_map_are_refused_host_side(self):
        class Never:
            def read_words(self, *a): raise AssertionError("a line was formed")
            def command(self, *a): raise AssertionError("a line was formed")
        p = l3.Plane(Never())
        for off in (po.PAYLOAD[0], po.TAG[0], po.CTRL, 0x2034, 0x0000):
            with self.assertRaises(bsn.SessionRefusal): p.read(off)
        with self.assertRaises(bsn.SessionRefusal): p.read_many(po.HW_COMMIT[0], 9)
        for off in (po.STATUS, po.HW_COMMIT[0], po.READOUT[0], 0x2034):
            with self.assertRaises(bsn.SessionRefusal): p.write(off, 0)

    def test_runner_never_holds_the_key(self):
        src = (REPO / "host/l3_runner.py").read_text()
        code = "\n".join(l.split("#")[0] for l in src.splitlines() if not l.lstrip().startswith(("#", '"""')))
        self.assertNotIn("KeyHolder(", code); self.assertNotIn("sg.KeyHolder", code)
        self.assertNotIn("_sign(", code)
        self.assertNotIn("key_path.read", code); self.assertNotIn("args.key.read", code)

    def test_ruling_text_is_the_l3_one_and_none_exists(self):
        self.assertEqual(l3.RULING_TEXT, "whole-of-probe P3-L3")
        # no UNCONSUMED ruling may lie around: every ruling file has its .consumed record
        rd = REPO / "rulings"
        if rd.exists():
            for r in rd.glob("*.json"):
                self.assertTrue(r.with_name(r.name + ".consumed").exists(), f"unconsumed ruling {r.name}")


if __name__ == "__main__":
    unittest.main()
