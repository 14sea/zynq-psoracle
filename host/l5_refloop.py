#!/usr/bin/env python3
"""The Python reference of the standalone application's main loop (D1 spec §3–§4).

This is the sequencing-and-refusals oracle the C application must mirror — the same role
the fake board played for L3: it proves the *state machine* (identity gate, per-candidate
transaction, epoch-end taxonomy, session brackets) host-side; it proves nothing about the
PL or the transport. The board is a duck-typed object (tests provide a FakeStandalonePL);
the notary is a callable line → reply-line (tests wire it straight to `NotaryRelay`).

Board interface expected:
    read_idcode() -> int            read_page() -> list[24 ints]      fclk0_hz() -> int
    axi_read(off) -> int            axi_write(off, val)               devcfg_healthy() -> bool
    stage(streams: list[list[int]]) reread() -> list[list[int]]
    write() -> list[dict]           readback_frame(far) -> list[101 ints]
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R)); sys.path.insert(0, str(R / "host"))
from validators import signer as sg  # noqa: E402
import l5_notary as n  # noqa: E402
import p3_gate as g  # noqa: E402
import p3_genome as gn  # noqa: E402
import p3_oracle as po  # noqa: E402
import run_log as rl  # noqa: E402

PAGE_MAGIC = 0x50334944
PAGE_WORDS = 24
PAGE_LAYOUT = 2
REQUIRED_IDCODE = 0x03722093
IDCODE_MASK = 0x0FFFFFFF


class LoopStop(Exception):
    """kind ∈ {STOPPED, PROTOCOL}; identity failures raise before the loop starts."""

    def __init__(self, kind: str, reason: str):
        super().__init__(f"{kind}: {reason}")
        self.kind, self.reason = kind, reason


# ------------------------------------------------------------------- the identity page


def _hex_words(hx: str) -> list[int]:
    return [int(hx[8 * i:8 * i + 8], 16) for i in range(len(hx) // 8)]


def build_identity_page(token: str, uboot_epoch: int, app_image_sha_lo32: int,
                        carrier_sha256: str, nonce_seen: int, status_seen: int,
                        seed: int, budget: int, flags: int) -> list[int]:
    words = ([PAGE_MAGIC, PAGE_LAYOUT] + _hex_words(token) + [uboot_epoch, app_image_sha_lo32]
             + _hex_words(carrier_sha256)
             + [nonce_seen & 0xFFFFFFFF, (nonce_seen >> 32) & 0xFFFFFFFF]
             + [status_seen, seed, budget, flags, 0])
    checksum = 0
    for w in words:
        checksum ^= w
    return words + [checksum]


def parse_identity_page(words: list[int]) -> dict:
    if len(words) != PAGE_WORDS:
        raise LoopStop("STOPPED", f"identity page has {len(words)} words, expected {PAGE_WORDS}")
    checksum = 0
    for w in words[:-1]:
        checksum ^= w
    if words[0] != PAGE_MAGIC or words[1] != PAGE_LAYOUT or words[-1] != checksum:
        raise LoopStop("STOPPED", "identity page magic/layout/checksum refused")
    return {"token": "".join(f"{w:08x}" for w in words[2:6]),
            "uboot_epoch": words[6], "app_image_sha_lo32": words[7],
            "carrier_sha256": "".join(f"{w:08x}" for w in words[8:16]),
            "nonce_seen": words[16] | words[17] << 32,
            "status_seen": words[18], "seed": words[19], "budget": words[20],
            "flags": words[21]}


# ------------------------------------------------------------------------ the reference


class RefLoop:
    def __init__(self, board, notary_send, manifest: dict, consts: dict, drop_budget: int = 16):
        self.board, self.send, self.manifest, self.consts = board, notary_send, manifest, consts
        self.drop_budget = drop_budget
        self.seq = 0
        self.records: list[dict] = []
        self.closing = {"restore": "not_reached", "baseline": "not_reached", "unsigned_control": "not_reached"}
        self.closing_negative: dict | None = None
        self.page: dict | None = None
        self.identity: dict | None = None
        base, roles = g.gc.pinned_frames(manifest)
        self.blank = {far: list(base[far]) for far, r in roles.items() if r == "target"}

    # -- identity (§3b) ---------------------------------------------------------------

    def _nonce(self) -> int:
        return self.board.axi_read(po.NONCE_LO) | self.board.axi_read(po.NONCE_HI) << 32

    def establish_identity(self) -> dict:
        idcode = self.board.read_idcode()
        page = parse_identity_page(self.board.read_page())
        st = self.board.axi_read(po.STATUS)
        nonce = self._nonce()
        findings = []
        if idcode & IDCODE_MASK != REQUIRED_IDCODE:
            findings.append(f"PSS_IDCODE {idcode:#010x} is not XC7Z010")
        if st & po.ST_RESERVED or not st >> po.ST["alive"] & 1:
            findings.append(f"STATUS {st:#010x} is not the P3 carrier answering")
        if not st >> po.ST["key_loaded"] & 1:
            findings.append("key_loaded is 0: not the provisioned carrier instance")
        if st >> po.ST["fault"] & 1 or st >> po.ST["recovery_required"] & 1:
            findings.append(f"fault/recovery before start (STATUS {st:#010x})")
        if nonce != page["nonce_seen"]:
            findings.append(f"nonce {nonce:016x} != the host's last observation {page['nonce_seen']:016x}")
        self.page = page
        self.identity = {"schema": "app_identity", "schema_version": "1.0.0",
                         "control_plane": "standalone", "pss_idcode": f"{idcode:#010x}",
                         "token": page["token"], "uboot_epoch": page["uboot_epoch"],
                         "carrier_sha256": page["carrier_sha256"],
                         "nonce_at_start": f"{nonce:016x}", "status_at_start": f"{st:#010x}",
                         "fclk0_hz_decoded": self.board.fclk0_hz(), "app_epoch": 0,
                         "findings": findings}
        if findings:
            raise LoopStop("STOPPED", "identity refused: " + "; ".join(findings))
        return self.identity

    # -- the notary round-trip (§4.3) --------------------------------------------------

    def _sign(self, genome_hex: str, nonce_hex: str) -> dict:
        req = {"schema": "sign_request", "schema_version": "1.0.0", "token": self.page["token"],
               "app_epoch": 0, "seq": self.seq, "genome": genome_hex, "nonce": nonce_hex}
        try:
            reply_line = self.send(n.build_line(n.T_SIGNREQ, self.seq, self.page["token"],
                                                n.encode_payload(req)))
        except n.ProtocolEnd as exc:
            raise LoopStop("PROTOCOL", str(exc)) from None
        if reply_line is None:
            raise LoopStop("PROTOCOL", "no reply from the notary")
        try:
            f = n.parse_line(reply_line)
        except (n.FrameError, n.CrcError) as exc:
            raise LoopStop("PROTOCOL", f"malformed reply: {exc}") from None
        if f["token"] != self.page["token"] or f["seq"] != self.seq:
            raise LoopStop("PROTOCOL", "reply token/seq mismatch")
        if f["type"] not in (n.T_SIGNOK, n.T_SIGNREF):
            raise LoopStop("PROTOCOL", f"unexpected reply type {f['type']}")
        return n.decode_payload(f["payload"])

    # -- one candidate (§4) ------------------------------------------------------------

    def _stage_and_witness(self, frames: dict[int, list[int]], commit: str) -> dict:
        streams = g.build_streams(frames, self.manifest)
        self.board.stage([s["words"] for s in streams])
        reread = self.board.reread()
        far_sets = {e["far_set"] for e in g.envelopes(self.manifest)}
        staged: dict[int, list[int]] = {}
        for s, rr in zip(streams, reread):
            far, frames5 = g.parse_stream(rr, far_sets)
            env = next(e for e in g.envelopes(self.manifest) if e["far_set"] == far)
            for k, f in enumerate(env["targets"]):
                staged[f] = frames5[k]
        staged_sha = rl.frames_hash(staged)
        stream_sha = hashlib.sha256(b"".join(w.to_bytes(4, "big") for rr in reread for w in rr)).hexdigest()
        oracle = {"schema": "app_oracle_record", "schema_version": "1.0.0", "seq": self.seq,
                  "staged_sha256": staged_sha, "staged_stream_sha256": stream_sha,
                  "readback_sha256": "00" * 32, "write": {"envelopes": []}, "audit_available": True}
        if staged_sha != commit:
            raise LoopStop("STOPPED", "LINK2_MISMATCH: staged frames are not the signed commit")
        writes = self.board.write()
        oracle["write"]["envelopes"] = writes
        if any(w.get("error_bits") for w in writes):
            raise LoopStop("STOPPED", "DEVCFG error bits after a write DMA")
        read_frames = {far: self.board.readback_frame(far) for far in sorted(frames)}
        oracle["readback_sha256"] = rl.frames_hash(read_frames)
        return oracle

    def _arm(self, reply: dict) -> tuple[dict, dict | None]:
        st = self.board.axi_read(po.STATUS)
        if st >> po.ST["fault"] & 1 or st >> po.ST["recovery_required"] & 1:
            raise LoopStop("STOPPED", f"STOP_AXI: fault before ARM (STATUS {st:#010x})")
        nonce_before = self._nonce()
        payload = sg.ArmPayload(bytes.fromhex(reply["commit"]),
                                tuple(int(t, 16) for t in reply["expected_tables"]),
                                nonce_before.to_bytes(8, "little"), bytes.fromhex(reply["tag"]))
        hb_before = self.board.axi_read(po.HEARTBEAT)
        words = payload.words()
        for off, w in zip(po.PAYLOAD, words[:20]):
            self.board.axi_write(off, w)
        for off, w in zip(po.TAG, words[20:]):
            self.board.axi_write(off, w)
        self.board.axi_write(po.CTRL, po.ARM_STROBE)
        st = self.board.axi_read(po.STATUS)
        fault = self.board.axi_read(po.FAULT)
        nonce_after = self._nonce()
        if nonce_after == nonce_before:
            raise LoopStop("STOPPED", "the nonce did not step: the PL did not consume this ARM")
        arm = {"nonce_before": f"{nonce_before:016x}", "nonce_after": f"{nonce_after:016x}",
               "status_after": f"{st:#010x}", "fault_after": fault,
               "key_loaded_observed": bool(st >> po.ST["key_loaded"] & 1)}
        if not st >> po.ST["cfg_valid_hw"] & 1:
            return arm, None
        score = {"hw_candidate_commit": po.commit_words_to_hex(
                     [self.board.axi_read(o) for o in po.HW_COMMIT]),
                 "functional_readout": [f"{t:016x}" for t in po.readout_words_to_tables(
                     [self.board.axi_read(o) for o in po.READOUT])],
                 "scores": [self.board.axi_read(o) for o in po.SCORES],
                 "heartbeat": {"before": hb_before, "after": self.board.axi_read(po.HEARTBEAT)}}
        return arm, score

    def _candidate(self, genome: int) -> dict:
        self.seq += 1
        genome_hex = gn.to_hex(genome)
        rec = {"schema": "loop_record", "schema_version": "1.0.0", "seq": self.seq,
               "genome": genome_hex, "outcome": None, "verified": "replayed-only", "evidence": {}}
        answer = self._sign(genome_hex, f"{self._nonce():016x}")
        if answer.get("schema") == "sign_refusal":
            rec["outcome"] = "REFUSED_BY_GATE"
            rec["evidence"]["sign_refusal"] = answer
            self.records.append(rec)
            return rec
        rec["evidence"]["sign_reply"] = answer
        frames = gn.frames_from_genome(genome, self.manifest)
        try:
            oracle = self._stage_and_witness(frames, answer["commit"])
        except LoopStop as stop:
            rec["outcome"] = "STOP_LINK2"
            self.records.append(rec)
            raise
        rec["evidence"]["app_oracle_record"] = oracle
        if oracle["readback_sha256"] != answer["commit"]:
            rec["outcome"] = "STOP_LINK3"
            self.records.append(rec)
            raise LoopStop("STOPPED", "LINK3_MISMATCH: the fabric did not read back as the candidate")
        arm, score = self._arm(answer)
        rec["evidence"]["arm"] = arm
        if score is None:
            rec["outcome"] = "REFUSED_BY_PL"
            self.records.append(rec)
            raise LoopStop("STOPPED", f"the PL refused the ARM (fault {arm['fault_after']})")
        rec["outcome"] = "SCORED"
        rec["evidence"]["score"] = score
        self.records.append(rec)
        return rec

    # -- the session (§4.0 brackets + §3c taxonomy) ------------------------------------

    def _closing_unsigned(self, reply: dict) -> None:
        nonce_before = self._nonce()
        payload = sg.ArmPayload(bytes.fromhex(reply["commit"]),
                                tuple(int(t, 16) for t in reply["expected_tables"]),
                                nonce_before.to_bytes(8, "little"), bytes(16))
        for off, w in zip(po.PAYLOAD, payload.words()[:20]):
            self.board.axi_write(off, w)
        for off, w in zip(po.TAG, payload.words()[20:]):
            self.board.axi_write(off, w)
        self.board.axi_write(po.CTRL, po.ARM_STROBE)
        st = self.board.axi_read(po.STATUS)
        fault = self.board.axi_read(po.FAULT)
        nonce_after = self._nonce()
        self.closing_negative = {"nonce_before": f"{nonce_before:016x}",
                                 "nonce_after": f"{nonce_after:016x}",
                                 "fault": fault, "status": f"{st:#010x}"}
        if st >> po.ST["cfg_valid_hw"] & 1:
            raise LoopStop("STOPPED", "KILL: the closing unsigned ARM validated — the interlock did not hold")
        self.closing["unsigned_control"] = "done"

    def _summary(self, kind: str, reason: str) -> dict:
        return {"schema": "session_summary", "schema_version": "1.0.0", "token": self.page["token"],
                "epoch_end": {"kind": kind, "reason": reason, "last_seq": self.seq},
                "counts": {"scored": sum(1 for r in self.records if r["outcome"] == "SCORED"),
                           "refused_by_gate": sum(1 for r in self.records if r["outcome"] == "REFUSED_BY_GATE")},
                "closing": dict(self.closing),
                "audit": {"audited": sum(1 for r in self.records if r["verified"] == "audited"),
                          "total": len(self.records)},
                "crc_dropped": 0, "drop_budget": self.drop_budget, "written_by": "app"}

    def run(self, genomes: list[int]) -> dict:
        blank = gn.blank_genome(self.manifest)
        log: dict = {"control_plane": "standalone"}
        try:
            log["app_identity"] = self.establish_identity()
            self._candidate(blank)                     # opening baseline
            for genome in genomes:
                self._candidate(genome)
            closing = self._candidate(blank)           # closing baseline = restore + score
            self.closing["restore"] = "done"
            self.closing["baseline"] = "done"
            self._closing_unsigned(closing["evidence"]["sign_reply"])
            summary = self._summary("COMPLETED", "budget")
        except LoopStop as stop:
            if self.identity is not None:
                log["app_identity"] = self.identity   # the refused identity is still evidence
            if stop.kind == "STOPPED" and self.board.devcfg_healthy():
                try:                                    # the mandatory finally: restore, no ARM
                    self._stage_and_witness(self.blank, g.gate(
                        g.build_streams(self.blank, self.manifest), self.manifest)["candidate_sha256"])
                    self.closing["restore"] = "done"
                except LoopStop:
                    pass
            self.closing_negative = None if stop.kind in ("STOPPED", "PROTOCOL") else self.closing_negative
            summary = self._summary(stop.kind, stop.reason)
        log["loop_records"] = self.records
        if self.closing_negative is not None:
            log["closing_negative"] = self.closing_negative
        log["session_summary"] = summary
        return log
