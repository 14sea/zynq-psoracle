#!/usr/bin/env python3
"""L3 — the whole chain on one candidate, host side (`docs/p3_architecture.md` §3 v0.2, §6 L3).

    ruling → session (identity, epoch, keyed-carrier setup load, plmark)
      link 1  host gate     : p3_gate over the three PCAP envelope streams   (pure)
      stage                 : mw.l every stream word into WR_BUF
      link 2  PS oracle     : md.l re-read of WR_BUF → frames hash + stream hash
      write                 : the P1-shaped devcfg DMA (buf|1 → PCAP), gated as P1 was
      link 3  PS oracle     : pinned PCAP readback of all twelve target frames
      arm                   : nonce from the PL → gate signer (separate process) → 24 words
                              → strobe → the PL's own verify/sweep/compare
      score                 : configuration_valid_hw, HW_COMMIT, FUNCTIONAL_READOUT, SCORE0‥5
    records: candidate, gate_verdict, oracle_record, arm_record, score_record, run_log
             (validators/records.py rules (i)–(v) are checked before the run log is written)

Authority, as pinned: the runner decides nothing about validity — the PL's latch does. The
runner's own checks are STOPs (no ARM is attempted after a failed link), never PASSes.
This module never imports the key holder; signing is a subprocess (`sign_arm.py`, D4).

Board contact is behind a ruling whose text is RULING_TEXT, claimed O_EXCL and consumed by
any outcome (psmap's rule). NO ruling of that text exists yet: the whole-line gate review
comes first (owner mandate 2026-08-29).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R / "scripts"))
sys.path.insert(0, str(R / "host"))
sys.path.insert(0, str(R / "imported/fabricmap/scripts"))
sys.path.insert(0, str(R))
import board_session as bsn  # noqa: E402
import pcap_probe_plan as pp  # noqa: E402
import pcap_probe_runner as pr  # noqa: E402
import pcap_write_plan as wp  # noqa: E402
import bitstream_frames as bf  # noqa: E402
import run_log as rl  # noqa: E402
import p3_gate as g  # noqa: E402
import p3_oracle as po  # noqa: E402
from validators import signer as sg  # noqa: E402  (ArmPayload only — no KeyHolder is ever constructed here)
from validators import records  # noqa: E402

TOOL_VERSION = "l3_runner.py/0.1.0"
RULING_TEXT = "whole-of-probe P3-L3"
WR_BUF = g.WR_BUF
STREAM_WORDS = g.STREAM_WORDS
LEGAL_WRITE = (WR_BUF | pp.DMA_HOLD_TAG, pp.PCAP_ENDPOINT, STREAM_WORDS, 0)
ARM_TIMEOUT_S = 10.0          # U-Boot md.l polls; the PL is done in < 200 cycles at 50 MHz
STOP_LINK2, STOP_LINK3, STOP_ARM, STOP_AXI = "LINK2_MISMATCH", "LINK3_MISMATCH", "ARM_REFUSED", "AXI_PRECONDITION"


class Stop(Exception):
    def __init__(self, verdict: str, detail: str, record: dict | None = None):
        super().__init__(f"{verdict}: {detail}")
        self.verdict, self.detail, self.record = verdict, detail, record


# ---------------------------------------------------------------- the signer, out of process


class SubprocessSigner:
    """Asks `sign_arm.py` (the gate-signer principal) for a tag. Holds no key."""

    def __init__(self, key_path: Path, script: Path = R / "host/sign_arm.py", signer_user: str | None = None):
        self.key_path, self.script, self.signer_user = key_path, script, signer_user

    def _ask(self, req: dict, key_path: Path | None = None) -> dict:
        cmd = [sys.executable, str(self.script), str(key_path or self.key_path)]
        if self.signer_user:                       # the boundary: a different OS user, via the one sudoers line
            cmd = ["sudo", "-n", "-u", self.signer_user] + cmd
        p = subprocess.run(cmd, input=json.dumps(req), capture_output=True, text=True, timeout=120)
        if p.returncode != 0:
            raise Stop(STOP_ARM, f"the gate signer refused: {p.stderr.strip()}")
        return json.loads(p.stdout)

    def provision(self, execute: bool = False, ruling: Path | None = None, alt_key_path: Path | None = None) -> dict:
        """Ask the signer to write K into the PL's write-once register over JTAG. The runner
        never sees the words. `execute` is a board action and needs the provisioning ruling."""
        ans = self._ask({"op": "provision", "execute": execute, "ruling": str(ruling) if ruling else None}, alt_key_path)
        self.key_id = ans["key_id"]
        return ans["provision"]

    def sign(self, gate_verdict: dict, commit: bytes, tables: list[int], nonce: bytes) -> sg.ArmPayload:
        req = {"op": "sign", "gate_verdict": gate_verdict, "candidate_commit": commit.hex(),
               "expected_tables": [f"{t:#018x}" for t in tables], "nonce": nonce.hex()}
        ans = self._ask(req)
        payload = sg.ArmPayload(commit, tuple(tables), nonce, bytes.fromhex(ans["tag"]))
        if payload.words() != ans["words"]:
            raise Stop(STOP_ARM, "signer words do not re-derive from its tag")
        self.key_id = ans["key_id"]
        return payload


# ---------------------------------------------------------------- the AXI plane, allowlisted


class Plane:
    """Every AXI access is checked against the L1 map before a line is formed: an undecoded
    address is SLVERR → data abort → reset on this board (P2), so it is refused host-side."""

    def __init__(self, session: bsn.BoardSession):
        self.session = session
        self.reads: list[dict] = []

    def read(self, off: int) -> int:
        return self.read_many(off, 1)[0]

    def read_many(self, first: int, n: int) -> list[int]:
        offs = [first + 4 * i for i in range(n)]
        bad = [o for o in offs if o not in po.READABLE]
        if bad:
            raise bsn.SessionRefusal(f"AXI read outside the readable map: {[hex(b) for b in bad]}")
        words = self.session.read_words(po.axi(first), n)
        self.reads.append({"offset": f"{first:#06x}", "words": [f"{w:#010x}" for w in words]})
        return words

    def write(self, off: int, value: int) -> None:
        if off not in po.WRITABLE:
            raise bsn.SessionRefusal(f"AXI write outside the writable map: {off:#06x}")
        self.session.command(f"mw.l {po.axi(off):#010x} {value & 0xFFFFFFFF:#010x} 1")


# ---------------------------------------------------------------- frame table of the P3 base


def load_p3_table(bit_path: Path, manifest: dict) -> dict:
    data = bit_path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    if sha != manifest["bitstream_sha256"]:
        raise bsn.SessionRefusal(f"bitstream {sha[:16]}… is not the manifest's {manifest['bitstream_sha256'][:16]}…")
    frames = bf.parse_frames(bit_path)["frames"]
    for far_hex in manifest["target_fars"]:
        if any(frames[int(far_hex, 16)]):
            raise bsn.SessionRefusal(f"target frame {far_hex} is not blank in this base")
    reverse: dict[str, list[int]] = {}
    for far, words in frames.items():
        reverse.setdefault(pr.frame_sha256(words), []).append(far)
    return {"frames": frames, "reverse": reverse, "sha256": sha, "bytes": len(data)}


# ---------------------------------------------------------------- stage + link 2


def ensure_dcache_off(session: bsn.BoardSession) -> str:
    """The D-cache MUST be off before anything is staged for a DMA: with it on, `mw.l` lands
    in L1/L2, the DMA reads stale DDR, and the `md.l` re-read (link 2) reads the cache — so
    link 2 "confirms" a stream the DMA never saw. Found on 17A6 2026-08-30 (L3 session #1 and
    the diagnostic: BLANK readback after WRITTEN; L2 had passed only because its read plan
    had already turned the cache off). psmap's read plan carries this step; the write path
    did not. Verified by content of the `dcache` reply, never assumed."""
    session.command("dcache off")
    reply = session.command("dcache").decode("ascii", "replace")
    if "Cache is OFF" not in reply:
        raise Stop(pr.PRECONDITION, f"D-cache is not off before staging: {reply.strip()!r}")
    return reply


def stage_and_reread(session: bsn.BoardSession, stream: list[int], far_sets: set[int],
                     tick=None, tick_every: int = 0) -> tuple[int, list[list[int]], list[int]]:
    """dcache off (verified) → mw.l every word → md.l the whole buffer back (link 2).
    Returns (far_set, five frames, the re-read words). A re-read that is not the stream is a
    STOP, before any DMA. `tick(i)` is called every `tick_every` words (L2's sub-samples)."""
    session.authorise(bsn.CONFIG_READ_CAPABILITY)
    ensure_dcache_off(session)
    for i, w in enumerate(stream):
        session.command(f"mw.l {WR_BUF + 4 * i:#010x} {w:#010x} 1")
        if tick and tick_every and (i + 1) % tick_every == 0:
            tick(i + 1)
    reread = session.read_words(WR_BUF, len(stream))
    if reread != stream:
        first = next(i for i, (a, b) in enumerate(zip(reread, stream)) if a != b)
        raise Stop(STOP_LINK2, f"staged word {first} reads {reread[first]:#010x}, sent {stream[first]:#010x}")
    far, frames = g.parse_stream(reread, far_sets)
    return far, frames, reread


# ---------------------------------------------------------------- write (P1's executor shape)


def write_script() -> list[dict]:
    s = [{"step": "ctrl-before", "cmd": f"md.l {pp.REG['CTRL']:#010x} 1"},
         {"step": "clear-write", "cmd": f"mw.l {pp.REG['INT_STS']:#010x} {pp.INT_STS_CLEAR_MASK:#010x} 1"},
         {"step": "clear-verify-write", "cmd": f"md.l {pp.REG['INT_STS']:#010x} 1"}]
    src, dst, sl, dl = LEGAL_WRITE
    for reg, val in (("DMA_SRC_ADDR", src), ("DMA_DEST_ADDR", dst), ("DMA_SRC_LEN", sl), ("DMA_DEST_LEN", dl)):
        s.append({"step": "dma-write", "cmd": f"mw.l {pp.REG[reg]:#010x} {val:#010x} 1"})
    s += [{"step": "wait-write", "cmd": f"md.l {pp.REG['INT_STS']:#010x} 1"},
          {"step": "ctrl-after", "cmd": f"md.l {pp.REG['CTRL']:#010x} 1"}]
    return s


def execute_write(session: bsn.BoardSession, name: str) -> dict:
    """P1's `execute_write_plan` loop over the already-staged buffer (same gates, same names)."""
    session.authorise(bsn.CONFIG_READ_CAPABILITY)
    plmark = session.check_plmark()
    stage = {"stage": name, "epoch": session.epoch, "plmark": plmark, "dma": [f"{x:#010x}" for x in LEGAL_WRITE],
             "observations": {}, "wait": None, "verdict": None}
    obs = stage["observations"]
    queued_at = None
    for step in write_script():
        nm, cmd = step["step"], step["cmd"]
        form, start, span = pp.parse_command(cmd)
        if form == "mw.l":
            session.command(cmd)
            if nm == "dma-write" and start == pp.REG["DMA_DEST_LEN"]:
                queued_at = time.monotonic()
            continue
        v = session.read_command(cmd, start, 1)[0]
        if nm == "ctrl-before":
            obs["ctrl_before"] = f"{v:#010x}"
            if v & pp.CTRL_MASK != pp.CTRL_REQUIRED:
                raise Stop(pr.PRECONDITION, f"CTRL {v:#010x} fails the masked gate before the write", stage)
        elif nm == "ctrl-after":
            obs["ctrl_after"] = f"{v:#010x}"
            if obs["ctrl_after"] != obs["ctrl_before"]:
                raise Stop(pr.PRECONDITION, f"CTRL changed across the write {obs['ctrl_before']} -> {obs['ctrl_after']}", stage)
        elif nm == "clear-verify-write":
            obs["int_sts_after_clear"] = f"{v:#010x}"
            if v & pp.INT_STS_CLEAR_MASK:
                raise Stop(pr.PRECONDITION, f"INT_STS {v:#010x} did not clear", stage)
        elif nm == "wait-write":
            polls = 1
            while True:
                if v & pp.INT_STS_ERROR_MASK:
                    stage["wait"] = {"int_sts": f"{v:#010x}", "polls": polls, "error_bits": pr.error_bit_names(v)}
                    raise Stop("OVERFLOW" if v & pr.INT_STS_RX_FIFO_OV else pr.DMA_ERROR,
                               f"write: INT_STS {v:#010x} {pr.error_bit_names(v)}", stage)
                if v & pp.INT_STS_D_P_DONE:
                    stage["wait"] = {"int_sts": f"{v:#010x}", "polls": polls,
                                     "elapsed_s": round(time.monotonic() - queued_at, 6)}
                    break
                if time.monotonic() > queued_at + pp.TIMEOUT_S:
                    stage["wait"] = {"int_sts": f"{v:#010x}", "polls": polls}
                    raise Stop("TIMEOUT", f"write: no D_P_DONE in {pp.TIMEOUT_S} s", stage)
                v = session.read_command(cmd, start, 1)[0]
                polls += 1
    stage["verdict"] = "WRITTEN"
    return stage


# ---------------------------------------------------------------- link 3


def readback_frame(session: bsn.BoardSession, table: dict, far: int, expected: list[int], name: str) -> dict:
    plan = pp.build_plan(far, pp.PINNED_DMA_ORDER, pr.SENTINEL)
    pr.validate_plan(plan)
    try:
        rec = pr.execute_plan(bsn.CONFIG_READ_CAPABILITY, session, plan, table, pr.frame_sha256(expected), name)
    except pr.ProbeStop as stop:
        raise Stop(STOP_LINK3, f"{far:#010x}: readback {stop.verdict}: {stop.detail}", stop.record) from None
    return rec


# ---------------------------------------------------------------- the ARM transaction


def arm_and_score(plane: Plane, signer, gate_verdict: dict, tables: list[int], holdout: bool) -> tuple[dict, dict | None]:
    status, fault = plane.read(po.STATUS), plane.read(po.FAULT)
    problems = []
    if status & po.ST_RESERVED or not status >> po.ST["alive"] & 1:
        problems.append(f"STATUS {status:#010x} is not the P3 carrier answering")
    if status >> po.ST["recovery_required"] & 1 or fault:
        problems.append(f"recovery_required/fault set before ARM (STATUS {status:#010x} FAULT {fault:#x})")
    if status >> po.ST["gate_busy"] & 1 or status >> po.ST["scorer_busy"] & 1:
        problems.append("gate or scorer busy before ARM")
    if problems:
        raise Stop(STOP_AXI, "; ".join(problems))
    key_loaded = bool(status >> po.ST["key_loaded"] & 1)
    nonce_int = plane.read(po.NONCE_LO) | plane.read(po.NONCE_HI) << 32
    nonce = nonce_int.to_bytes(8, "little")
    commit = bytes.fromhex(gate_verdict["candidate_sha256"])
    payload = signer.sign(gate_verdict, commit, tables, nonce)
    words = payload.words()
    hb_before = plane.read(po.HEARTBEAT)
    for off, w in zip(po.PAYLOAD, words[:20]):
        plane.write(off, w)
    for off, w in zip(po.TAG, words[20:]):
        plane.write(off, w)
    arm_record = {"schema": "arm_record", "schema_version": "1.0.0",
                  "nonce": f"{nonce_int:016x}", "candidate_commit": commit.hex(),
                  "expected_tables": [f"{t:016x}" for t in tables], "tag": payload.tag.hex(),
                  "signer": {"principal": "gate-signer", "key_id": getattr(signer, "key_id", None)},
                  "axi_before": {"status": f"{status:#010x}", "fault": f"{fault:#x}"},
                  "key_loaded_observed": key_loaded,
                  "mode_holdout": holdout, "armed_at": time.time(), "_payload": payload}
    plane.write(po.CTRL, po.ARM_STROBE | (po.MODE_HOLDOUT if holdout else 0))
    deadline = time.monotonic() + ARM_TIMEOUT_S
    while True:
        st = plane.read(po.STATUS)
        busy = st >> po.ST["gate_busy"] & 1 or st >> po.ST["scorer_busy"] & 1
        settled = (st >> po.ST["fault"] & 1) or (st >> po.ST["scorer_done"] & 1)
        if not busy and settled:
            break
        if time.monotonic() > deadline:
            raise Stop(STOP_ARM, f"the PL did not settle after ARM (STATUS {st:#010x})", arm_record)
    fault_after = plane.read(po.FAULT)
    nonce_after = plane.read(po.NONCE_LO) | plane.read(po.NONCE_HI) << 32
    arm_record["axi_after"] = {"status": f"{st:#010x}", "fault": f"{fault_after:#x}", "nonce": f"{nonce_after:016x}"}
    if nonce_after == nonce_int:
        raise Stop(STOP_ARM, "the nonce did not step: the PL did not consume this ARM", arm_record)
    valid = bool(st >> po.ST["cfg_valid_hw"] & 1)
    if not valid:
        arm_record["pl_refusal"] = {"fault": fault_after, "name": po.FAULT_NAMES.get(fault_after, "?")}
        return arm_record, None
    hw_commit = plane.read_many(po.HW_COMMIT[0], 8)
    readout = po.readout_words_to_tables(plane.read_many(po.READOUT[0], 12))
    scores = plane.read_many(po.SCORES[0], 6)
    hb_after = plane.read(po.HEARTBEAT)
    score = {"schema": "score_record", "schema_version": "1.0.0",
             "configuration_valid_hw": True, "hw_candidate_commit": po.commit_words_to_hex(hw_commit),
             "functional_readout": [f"{t:016x}" for t in readout], "scores": scores,
             "heartbeat": {"before": hb_before, "after": hb_after}, "mode_holdout": holdout,
             "status": f"{st:#010x}"}
    return arm_record, score


# ---------------------------------------------------------------- on-board negative controls (§6 L3)


def negative_control(plane: Plane, kind: str, signer, positive: sg.ArmPayload, phen: dict, consts: dict,
                     arm_record_sha: str) -> dict:
    """After the positive case, one control per session (a fault is sticky until reset).
    unsigned: zero tag; replay: the positive payload again (nonce has stepped); other_candidate:
    a valid tag for the blank candidate with the positive commit staged (tag for X, payload says Y);
    wrong_table: the blank candidate correctly signed — tag_ok, fabric differs → F_ARM_TABLE."""
    if kind not in records.NEGATIVE_KINDS:
        raise Stop(STOP_ARM, f"unknown negative control {kind!r}")
    nonce_int = plane.read(po.NONCE_LO) | plane.read(po.NONCE_HI) << 32
    nonce = nonce_int.to_bytes(8, "little")
    if kind == "unsigned":
        payload = sg.ArmPayload(positive.candidate_commit, positive.expected_tables, nonce, bytes(16))
    elif kind == "replay":
        payload = positive
    else:
        base, roles = g.gc.pinned_frames(phen)
        blank = {far: list(base[far]) for far, r in roles.items() if r == "target"}
        bv = g.gate(g.build_streams(blank, phen), phen)
        tables = po.expected_tables(blank, consts)
        signed = signer.sign(bv, bytes.fromhex(bv["candidate_sha256"]), tables, nonce)
        payload = signed if kind == "wrong_table" else \
            sg.ArmPayload(positive.candidate_commit, signed.expected_tables, nonce, signed.tag)
    words = payload.words()
    for off, w in zip(po.PAYLOAD, words[:20]):
        plane.write(off, w)
    for off, w in zip(po.TAG, words[20:]):
        plane.write(off, w)
    plane.write(po.CTRL, po.ARM_STROBE)
    deadline = time.monotonic() + ARM_TIMEOUT_S
    while True:
        st = plane.read(po.STATUS)
        busy = st >> po.ST["gate_busy"] & 1 or st >> po.ST["scorer_busy"] & 1
        if not busy and ((st >> po.ST["fault"] & 1) or (st >> po.ST["scorer_done"] & 1) or (st >> po.ST["cfg_valid_hw"] & 1)):
            break
        if time.monotonic() > deadline:
            raise Stop(STOP_ARM, f"negative control {kind}: the PL did not settle (STATUS {st:#010x})")
    fault = plane.read(po.FAULT)
    nonce_after = plane.read(po.NONCE_LO) | plane.read(po.NONCE_HI) << 32
    valid = bool(st >> po.ST["cfg_valid_hw"] & 1)
    scored = bool(st >> po.ST["scorer_armed"] & 1)
    rec = {"schema": "negative_control", "schema_version": "1.0.0", "kind": kind,
           "arm_record_sha256": arm_record_sha, "nonce": f"{nonce_int:016x}",
           "nonce_after": f"{nonce_after:016x}", "status": f"{st:#010x}",
           "configuration_valid_hw": valid, "fault": fault, "scored": scored,
           "refused_as_expected": (not valid) and (not scored) and fault == records.EXPECTED_FAULT[kind]}
    if valid or scored:
        raise Stop("KILL", f"negative control {kind!r} validated/scored (STATUS {st:#010x}) — the interlock did not hold", rec)
    if nonce_after == nonce_int:
        rec["refused_as_expected"] = False
        rec["note"] = "nonce not consumed"
    return rec


# ---------------------------------------------------------------- the chain


def run_l3(session: bsn.BoardSession, out_dir: Path, ruling: dict, cfg: dict) -> dict:
    """cfg: manifest, bitstream (Path), candidate (frames dict), signer, holdout, consts, table."""
    manifest, consts = cfg["manifest"], cfg["consts"]
    table = cfg.get("table") or load_p3_table(cfg["bitstream"], manifest)
    summary = {"tool": TOOL_VERSION, "ruling": ruling, "stages": {}, "outcome": None,
               "manifest_sha256": hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest(),
               "bitstream_sha256": table["sha256"]}
    recs: list[dict] = []
    phen = g.load_manifest()
    try:
        # ---- link 1, before any board contact
        streams = g.build_streams(cfg["candidate"], phen)
        verdict = g.gate(streams, phen)
        if not verdict["writable"]:
            raise Stop("GATE_REFUSED", f"{len(verdict['findings'])} finding(s): {[f['kind'] for f in verdict['findings']]}")
        tables = po.expected_tables(cfg["candidate"], consts)
        candidate = {"schema": "candidate", "schema_version": "1.0.0",
                     "carrier_manifest_sha256": summary["manifest_sha256"],
                     "frames": [{"far": far, "words": cfg["candidate"][far]} for far in sorted(cfg["candidate"])],
                     "candidate_sha256": verdict["candidate_sha256"],
                     "stream_words": [w for s in streams for w in s["words"]], "sequence_sha256": verdict["sequence_sha256"]}
        records.validate(candidate); records.validate(verdict)
        # ---- session
        summary["precheck"] = pr.precheck(session)
        summary["identity"] = session.verify_identity()
        summary["setup_load"] = session.load_carrier(bsn.SETUP_LOAD_CAPABILITY, cfg["bitstream"],
                                                     manifest["bitstream_sha256"], out_dir / "ymodem.log")
        verdict = dict(verdict, epoch=session.epoch)
        recs += [candidate, verdict]
        # ---- key provisioning by the signer principal (JTAG mem-AP; never through this console)
        neg = cfg.get("negative")
        if neg != "unprovisioned":
            prov = cfg["signer"].provision(execute=cfg.get("provision_execute", False),
                                           ruling=cfg.get("provision_ruling"),
                                           alt_key_path=cfg.get("wrong_key_path") if neg == "wrong_key" else None)
            summary["provisioning"] = prov
        st = Plane(session).read(po.STATUS)
        summary["key_loaded_observed"] = bool(st >> po.ST["key_loaded"] & 1)
        if neg != "unprovisioned" and not summary["key_loaded_observed"]:
            raise Stop("KEY_NOT_LOADED", f"STATUS {st:#010x}: key_loaded is 0 after provisioning; no ARM")
        # ---- stage, link 2, write — per envelope
        far_sets = {e["far_set"] for e in g.envelopes(phen)}
        staged: dict[int, list[int]] = {}
        reread_all: list[int] = []
        writes = []
        for s in streams:
            far, frames, reread = stage_and_reread(session, s["words"], far_sets)
            env = next(e for e in g.envelopes(phen) if e["far_set"] == far)
            for k, f in enumerate(env["targets"]):
                staged[f] = frames[k]
            reread_all += reread
            wrec = execute_write(session, f"L3_write_{s['index']}")
            writes.append(wrec)
            pr.write_record(out_dir, wrec["stage"], wrec)
            summary["stages"][wrec["stage"]] = wrec["verdict"]
        staged_sha = rl.frames_hash(staged)
        if staged_sha != verdict["candidate_sha256"]:
            raise Stop(STOP_LINK2, "the frames re-read from DDR are not the gate's candidate")
        # ---- link 3
        # link 3 reads ALL twelve frames before judging (reads are non-destructive): a stop then
        # names every frame that did not read back as the candidate — session #1 (2026-08-30)
        # stopped at the first BLANK and left the other eleven unobserved.
        read_frames: dict[int, list[int]] = {}
        readbacks = []
        mismatches = []
        for far in sorted(cfg["candidate"]):
            try:
                rec = readback_frame(session, table, far, cfg["candidate"][far], f"L3_read_{far:#010x}")
            except Stop as stop:
                rec = stop.record or {"stage": f"L3_read_{far:#010x}", "verdict": "NO_RECORD", "detail": stop.detail}
                mismatches.append(f"{far:#010x}: {rec.get('verdict')}")
            pr.write_record(out_dir, rec["stage"], rec)
            summary["stages"][rec["stage"]] = rec["verdict"]
            if rec.get("readout"):
                read_frames[far] = [int(w, 16) for w in rec["readout"]][pp.FRAME_WORDS:2 * pp.FRAME_WORDS]
            readbacks.append({"far": f"{far:#010x}", "frame_sha256": rec.get("frame_sha256"), "verdict": rec.get("verdict"),
                              "matched_far": rec.get("matched_far")})
        readback_sha = rl.frames_hash(read_frames) if len(read_frames) == 12 else "00" * 32
        oracle = {"schema": "oracle_record", "schema_version": "1.0.0",
                  "session": {"boardid": summary["identity"]["parsed"]["boardid"], "epoch": session.epoch,
                              "plmark": session.plmark, "identity_sha256": hashlib.sha256(json.dumps(summary["identity"], sort_keys=True, default=str).encode()).hexdigest()},
                  "candidate_sha256": verdict["candidate_sha256"],
                  "staged_sha256": staged_sha,
                  "staged_stream_sha256": hashlib.sha256(b"".join(w.to_bytes(4, "big") for w in reread_all)).hexdigest(),
                  "write": {"dma": [f"{x:#010x}" for x in LEGAL_WRITE], "envelopes": writes},
                  "readback_sha256": readback_sha, "readback_records": readbacks,
                  "configuration_valid_hw_expected": readback_sha == verdict["candidate_sha256"],
                  "transport_rereads": list(session.rereads)}
        records.validate(oracle); recs.append(oracle)
        if readback_sha != verdict["candidate_sha256"]:
            raise Stop(STOP_LINK3, f"{len(mismatches)}/12 frames did not read back as the candidate ({'; '.join(mismatches)}); no ARM")
        # ---- arm + score
        plane = Plane(session)
        arm, score = arm_and_score(plane, cfg["signer"], verdict, tables, cfg.get("holdout", False))
        arm_payload = arm.pop("_payload")
        arm.update(oracle_record_sha256=records.canonical_sha256(oracle),
                   gate_verdict_sha256=records.canonical_sha256(verdict), epoch=session.epoch)
        records.validate(arm); recs.append(arm)
        summary["stages"]["L3_arm"] = "ARMED" if score else f"REFUSED_BY_PL {arm.get('pl_refusal')}"
        if neg in records.PRE_CONTROLS:
            # the positive attempt IS the control: it must have been refused with the kind's fault
            if score is not None:
                raise Stop("KILL", f"pre-positive control {neg!r} armed and scored — the interlock did not hold")
            fault_seen = arm["pl_refusal"]["fault"]
            ctl = {"schema": "negative_control", "schema_version": "1.0.0", "kind": neg,
                   "arm_record_sha256": records.canonical_sha256(arm), "nonce": arm["nonce"],
                   "nonce_after": arm["axi_after"]["nonce"], "status": arm["axi_after"]["status"],
                   "configuration_valid_hw": False, "fault": fault_seen, "scored": False,
                   "refused_as_expected": fault_seen == records.EXPECTED_FAULT[neg]}
            records.validate(ctl); recs.append(ctl)
            summary["stages"][f"L3_negative_{neg}"] = "REFUSED" if ctl["refused_as_expected"] else "NOT_REFUSED_AS_EXPECTED"
            summary["outcome"] = ("PASS" if ctl["refused_as_expected"]
                                  else f"HOLD: control {neg} fault {fault_seen} != expected {records.EXPECTED_FAULT[neg]}")
            return summary
        if score is None:
            raise Stop(STOP_ARM, f"the PL refused the ARM: {arm['pl_refusal']}")
        score.update(arm_record_sha256=records.canonical_sha256(arm),
                     host_prediction=po.predict_scores(tables, consts, cfg.get("holdout", False)))
        score["match"] = score["host_prediction"] == score["scores"]
        records.validate(score); recs.append(score)
        summary["stages"]["L3_score"] = "SCORED"
        summary["outcome"] = "PASS" if score["match"] else "HOLD: PL scores differ from the host prediction"
        if cfg.get("negative"):
            neg = negative_control(plane, cfg["negative"], cfg["signer"], arm_payload, phen, consts,
                                   records.canonical_sha256(arm))
            records.validate(neg); recs.append(neg)
            summary["stages"][f"L3_negative_{cfg['negative']}"] = "REFUSED" if neg["refused_as_expected"] else "NOT_REFUSED_AS_EXPECTED"
            if not neg["refused_as_expected"]:
                summary["outcome"] = f"HOLD: negative control {cfg['negative']} fault {neg['fault']} != expected {records.EXPECTED_FAULT[cfg['negative']]}"
    except Stop as stop:
        if stop.record is not None:
            pr.write_record(out_dir, "stop", stop.record)
        summary["outcome"] = (f"KILL {stop.detail}" if stop.verdict == "KILL" else f"STOP {stop.verdict}: {stop.detail}")
    except bsn.SessionRefusal as refusal:
        summary["outcome"] = f"REFUSED: {refusal}"
    except Exception as exc:
        import traceback
        summary["outcome"] = f"CRASHED host-side: {type(exc).__name__}: {exc}"
        summary["traceback"] = traceback.format_exc()
    finally:
        log = {"schema": "run_log", "schema_version": "1.0.0", "tool": TOOL_VERSION,
               "ruling_sha256": hashlib.sha256(json.dumps(ruling, sort_keys=True).encode()).hexdigest(),
               "records": recs, "epoch_final": session.epoch, "outcome": summary["outcome"]}
        try:
            summary["run_log_validation"] = records.validate_run_log(log)
        except records.RecordError as exc:
            summary["run_log_validation"] = f"REJECTED: {exc}"
            summary["outcome"] = f"KILL run_log rejected: {exc} (was: {summary['outcome']})"
        pr.write_record(out_dir, "run_log", log)
        summary["uart_log"] = session.log
        summary["disruptions"] = session.disruptions
        summary["transport_rereads"] = session.rereads
        summary["epoch_final"] = session.epoch
        pr.write_record(out_dir, "summary", summary)
    return summary


# ---------------------------------------------------------------- entry


def _record_pk(pk_ruling: Path, outcome: str) -> None:
    """Never BEFORE the run (attempt 1 of session #2 pre-claimed and the signer refused)."""
    try:
        pk_consumed = Path(str(pk_ruling) + ".consumed")
        if not pk_consumed.exists():
            pr.claim_ruling(Path(pk_ruling))
        pr.record_outcome(pk_consumed, f"provisioning session outcome: {outcome}")
    except OSError:
        pass


def _install_sigterm():
    """A SIGTERM (a shell timeout, a killed terminal) must still write the summary and the
    ruling outcome: it becomes a SessionRefusal inside the chain (L2 run #1, 2026-08-29)."""
    import signal

    def _h(signum, frame):
        raise bsn.SessionRefusal(f"signal {signum} received by the runner (host-side kill)")
    signal.signal(signal.SIGTERM, _h); signal.signal(signal.SIGHUP, _h)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ruling", type=Path, required=True, help=f"ruling text must be {RULING_TEXT!r}")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--bitstream", type=Path, required=True)
    ap.add_argument("--key", type=Path, default=Path("/var/lib/p3signer/keys/K.bin"),
                    help="the signer's key path, passed through to the signer subprocess; unreadable by this user")
    ap.add_argument("--candidate", type=Path, default=None, help="candidate JSON (frames); default: the known answer")
    ap.add_argument("--holdout", action="store_true")
    ap.add_argument("--negative", choices=records.NEGATIVE_KINDS, default=None,
                    help="one on-board negative control per session (a fault is sticky until reset); "
                         "unprovisioned/wrong_key run INSTEAD of the positive ARM")
    ap.add_argument("--provision-ruling", type=Path, default=None,
                    help="ruling 'provisioning P3-K' handed to the signer; without it provisioning is only prepared")
    ap.add_argument("--wrong-key", type=Path, default=None, help="signer-owned second key file for --negative wrong_key")
    ap.add_argument("--boundary", type=Path, required=True,
                    help="principal_boundary record from host/verify_principal_boundary.py (run as the runner user); "
                         "must be all-passed and < 6 h old, or the runner refuses to start")
    ap.add_argument("--signer-user", default="p3signer")
    ap.add_argument("--port", default=bsn.PORT)
    args = ap.parse_args(argv)
    try:
        ruling = pr.check_ruling(args.ruling, text=RULING_TEXT)
        if args.out.exists():
            raise bsn.SessionRefusal(f"{args.out} exists; evidence is never replaced")
        if shutil.which("sb") is None:
            raise bsn.SessionRefusal("`sb` is not installed")
        manifest = json.loads(args.manifest.read_text())
        records.validate(manifest)
        boundary = json.loads(args.boundary.read_text())
        records.boundary_established(boundary, time.time())
        if boundary["signer_user"] != args.signer_user:
            raise bsn.SessionRefusal(f"boundary record is for signer {boundary['signer_user']!r}, not {args.signer_user!r}")
        phen = g.load_manifest()
        cand = g.known_answer_candidate(phen) if args.candidate is None else {
            int(f["far"], 16): [int(w, 16) for w in f["words"]] for f in json.loads(args.candidate.read_text())["frames"]}
        cfg = {"manifest": manifest, "bitstream": args.bitstream, "candidate": cand,
               "signer": SubprocessSigner(args.key, signer_user=args.signer_user), "holdout": args.holdout, "consts": po.load_constants(),
               "negative": args.negative, "provision_execute": args.provision_ruling is not None,
               "provision_ruling": args.provision_ruling, "wrong_key_path": args.wrong_key}
        if args.negative == "wrong_key" and args.wrong_key is None:
            raise bsn.SessionRefusal("--negative wrong_key needs --wrong-key")
        cfg["table"] = load_p3_table(args.bitstream, manifest)
        if not g.gate(g.build_streams(cand, phen), phen)["writable"]:
            raise bsn.SessionRefusal("the gate refuses this candidate; nothing is sent")
    except (bsn.SessionRefusal, pr.ProbeStop, ValueError, records.RecordError, OSError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    consumed = pr.claim_ruling(args.ruling)
    args.out.mkdir(parents=True)
    _install_sigterm()
    outcome = "CRASHED before a summary was written"
    try:
        transport = bsn.SerialTransport(args.port)
        try:
            session = bsn.BoardSession(transport)
            outcome = run_l3(session, args.out, ruling, cfg)["outcome"]
        finally:
            transport.close()
    except bsn.SessionRefusal as exc:
        outcome = f"REFUSED: {exc}"
    finally:
        pr.record_outcome(consumed, outcome)
        if args.provision_ruling:            # the P3-K ruling: the signer consumed it at execution; record the session outcome beside it
            _record_pk(args.provision_ruling, outcome)
    print(outcome, file=sys.stderr if outcome != "PASS" else sys.stdout)
    return 0 if outcome == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
