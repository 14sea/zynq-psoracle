#!/usr/bin/env python3
"""Link 1 for P3 — the host gate — and the PCAP envelope streams it judges.

The judgement is fabricmap's, verbatim: `target_frame_findings` (whitelist-only bits plus
a correctly recomputed ECC) and `flush_frame_findings` (verbatim, ECC included) from the
imported `gate_candidate.py`, against the imported `phenotype_manifest.json` whose fifteen
pinned frames are byte-identical in the P3 base. What is new is the transport: a candidate
is written over PCAP as three envelopes — one FAR-set per sync..DESYNC stream, an FDRI burst
of 505 words (four target frames + the flush frame the device's auto-increment reaches
next), the shape zynq-psmap's P1 proved for one frame. The gate parses the streams it
will send, never the intent (preregistration §6 item 5), and its findings are bucketed by
kind (fabricmap's KINDS: stream grammar → `structure`, envelope set → `addressing`), never by message text.

Hash domains are fabricmap's `run_log`: `candidate_sha256` = frames_hash over the
FAR-ordered canonical set of ALL twelve target frames (a candidate rewrites every target
frame, not only the ones it changed — the manifest's rule); `sequence_sha256` = sha256
over the three streams' words in order.
"""

from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R / "imported/fabricmap/scripts"))
sys.path.insert(0, str(R / "scripts"))
import gate_candidate as gc  # noqa: E402  (fabricmap, imported byte-for-byte)
import run_log as rl  # noqa: E402
import pcap_write_plan as wp  # noqa: E402  (psmap: stream words, DMA shape, guards)

MANIFEST = R / "imported/fabricmap/gate_runs/claimb_round1_carrier_2026_08_13_erratum006/phenotype_manifest.json"
FRAME_WORDS = 101
ENVELOPE_FRAMES = 5           # 4 targets + 1 flush
FDRI_WORDS = ENVELOPE_FRAMES * FRAME_WORDS   # 505
WR_BUF = wp.WR_BUF
STREAM_WORDS = wp.FDRI_DATA_OFFSET + FDRI_WORDS + 2 + 4   # 534


def load_manifest(path: Path = MANIFEST) -> dict:
    return json.loads(path.read_text())


def envelopes(manifest: dict) -> list[dict]:
    return [{"index": e["index"], "far_set": int(e["far_set"], 16),
             "targets": [int(f, 16) for f in e["target_fars"]], "flush": int(e["flush_far"], 16)}
            for e in manifest["write_envelope"]["envelopes"]]


def envelope_stream(far_set: int, frames5: list[list[int]]) -> list[int]:
    """The P1 stream shape with a 505-word FDRI: dummy×8, sync, RCRC, IDCODE, WCFG, FAR, FDRI, data, DESYNC."""
    if len(frames5) != ENVELOPE_FRAMES or any(len(f) != FRAME_WORDS for f in frames5):
        raise ValueError("an envelope is exactly five 101-word frames")
    data = [w for f in frames5 for w in f]
    return ([wp.DUMMY] * 8 + [wp.SYNC, wp.NOOP,
            wp.t1(True, wp.REG_CMD, 1), wp.CMD_RCRC, wp.NOOP, wp.NOOP,
            wp.t1(True, wp.REG_IDCODE, 1), wp.IDCODE_XC7Z010,
            wp.t1(True, wp.REG_CMD, 1), wp.CMD_WCFG, wp.NOOP,
            wp.t1(True, wp.REG_FAR, 1), far_set,
            wp.t1(True, wp.REG_FDRI, 0), wp.t2_write(FDRI_WORDS)]
            + data + [wp.t1(True, wp.REG_CMD, 1), wp.CMD_DESYNC, wp.NOOP, wp.NOOP, wp.NOOP, wp.NOOP])


def parse_stream(words: list[int], far_sets: set[int]) -> tuple[int, list[list[int]]]:
    """Literal walk: the same grammar as psmap's `validate_write_stream`, with a 505-word FDRI
    and a FAR from the envelope set. Returns (far_set, five frames). Raises on anything else."""
    if len(words) != STREAM_WORDS:
        raise ValueError(f"stream has {len(words)} words, pinned {STREAM_WORDS}")
    if words[:8] != [wp.DUMMY] * 8 or words[8] != wp.SYNC:
        raise ValueError("stream must open with eight dummies and the sync word")
    i, cmds, far, frames = 9, [], None, None
    while i < len(words):
        w = words[i]
        if w == wp.NOOP:
            i += 1; continue
        if (w >> 29) != 1 or ((w >> 27) & 3) != 2:
            raise ValueError(f"word {w:#010x} at {i}: only type-1 writes are permitted")
        reg, count = (w >> 13) & 0x3FFF, w & 0x7FF
        if reg not in wp.ALLOWED_WRITE_REGS:
            raise ValueError(f"write to {'CRC' if reg == wp.REG_CRC else reg} at {i} is not permitted")
        if reg == wp.REG_CMD:
            if words[i + 1] not in wp.ALLOWED_CMDS:
                raise ValueError(f"command {words[i + 1]:#x} ({wp.FORBIDDEN_CMD_NAMES.get(words[i + 1], '?')}) is forbidden")
            cmds.append(words[i + 1]); i += 2
        elif reg == wp.REG_IDCODE:
            if words[i + 1] != wp.IDCODE_XC7Z010:
                raise ValueError("IDCODE is not the XC7Z010's")
            i += 2
        elif reg == wp.REG_FAR:
            if words[i + 1] not in far_sets:
                raise ValueError(f"FAR {words[i + 1]:#010x} is not an envelope FAR-set")
            far = words[i + 1]; i += 2
        else:
            if count != 0 or (words[i + 1] >> 29) != 2 or (words[i + 1] & 0x07FFFFFF) != FDRI_WORDS:
                raise ValueError("FDRI must be type-1 count 0 then type-2 of exactly 505 words")
            if far is None:
                raise ValueError("FDRI before FAR")
            if frames is not None:
                raise ValueError("a second FDRI burst")
            data = words[i + 2:i + 2 + FDRI_WORDS]
            frames = [data[k * FRAME_WORDS:(k + 1) * FRAME_WORDS] for k in range(ENVELOPE_FRAMES)]
            i += 2 + FDRI_WORDS
    if cmds != [wp.CMD_RCRC, wp.CMD_WCFG, wp.CMD_DESYNC] or frames is None:
        raise ValueError("stream must be RCRC, WCFG, one FDRI, DESYNC")
    return far, frames


def build_streams(candidate_frames: dict[int, list[int]], manifest: dict) -> list[dict]:
    """Three envelope streams from a full candidate (all twelve target frames present)."""
    base, roles = gc.pinned_frames(manifest)
    out = []
    for e in envelopes(manifest):
        frames5 = [candidate_frames[f] for f in e["targets"]] + [base[e["flush"]]]
        out.append({"index": e["index"], "far_set": e["far_set"], "targets": e["targets"], "flush": e["flush"],
                    "words": envelope_stream(e["far_set"], frames5)})
    return out


def gate(streams: list[dict], manifest: dict) -> dict:
    """Parse the streams that will be sent; judge every frame with fabricmap's rules."""
    base, roles = gc.pinned_frames(manifest)
    allowed = gc.whitelist_by_far(manifest)
    far_sets = {e["far_set"] for e in envelopes(manifest)}
    findings: list[dict] = []
    frames_seen: dict[int, list[int]] = {}
    seen_sets = []
    for s in streams:
        try:
            far, frames = parse_stream(s["words"], far_sets)
        except ValueError as exc:
            findings.append(gc.finding("structure", str(exc), envelope=s.get("index")))
            continue
        seen_sets.append(far)
        env = next(e for e in envelopes(manifest) if e["far_set"] == far)
        for k, f in enumerate(env["targets"]):
            findings += gc.target_frame_findings(f, base[f], frames[k], allowed.get(f, set()))
            frames_seen[f] = frames[k]
        findings += gc.flush_frame_findings(env["flush"], base[env["flush"]], frames[4])
    expected_sets = sorted(far_sets)
    if sorted(seen_sets) != expected_sets:
        findings.append(gc.finding("addressing", f"envelopes present {sorted(map(hex, seen_sets))}, expected all of {list(map(hex, expected_sets))}"))
    writable = not findings
    candidate_sha = rl.frames_hash(frames_seen) if len(frames_seen) == 12 else None
    seq = hashlib.sha256(b"".join(struct.pack(">I", w) for s in streams for w in s["words"])).hexdigest()
    return {"schema": "gate_verdict", "schema_version": "1.0.0",
            "candidate_sha256": candidate_sha, "sequence_sha256": seq, "writable": writable,
            "findings": findings,
            "gate_tool": {"name": "host/p3_gate.py", "frame_rules": "zynq-fabricmap gate_candidate.py",
                          "source_commit": "71666b02d526a6f2c641f1e0aebc15dac0417d4f"},
            "manifest_sha256": hashlib.sha256(MANIFEST.read_bytes()).hexdigest()}


def known_answer_candidate(manifest: dict) -> dict[int, list[int]]:
    """fabricmap's LUT0 known answer: its four touched frames over the pinned base for the rest."""
    ka = json.loads((R / "imported/fabricmap/gate_runs/claimb_round1_known_answer_2026_08_14/known_answer.json").read_text())
    base, roles = gc.pinned_frames(manifest)
    cand = {f: list(base[f]) for f, r in roles.items() if r == "target"}
    for rec in ka["candidate"]["touched_frames"]:
        cand[int(rec["far"], 16)] = [int(w, 16) for w in rec["words"]]
    return cand
