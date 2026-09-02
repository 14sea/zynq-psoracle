#!/usr/bin/env python3
"""Console byte-loss statistics over the L6 sessions (design review 2026-09-01, item 2;
extended in the rec-v3 batch to every session and every frame type).

Counts, per session and in total: bytes received, frames received by type, valid lines
by type, loss events (every P3L5 line that failed CRC or was malformed, of ANY type, with
seq, chunk where it has one, position and the bytes missing against a normal line of that
type/chunk), and the fraction of zero words in the audit payloads (dense 1.0.0 and sparse
2.0.0 alike). Exposure and events only — it draws no root-cause conclusion: three of six
events landed inside full-size push-era audit lines, one inside a pull-era REC line, and
with that few a position is not a pattern.
"""
from __future__ import annotations

import base64
import json
import statistics
import sys
import zlib
from pathlib import Path

R = Path(__file__).resolve().parent.parent
SESSIONS = ["evidence/l6_17A6_2026-09-01-06-C1", "evidence/l6_17A6_2026-09-01-07-C1", "evidence/l6_17A6_2026-09-01-08-C1",
            "evidence/l6_17A6_2026-09-01-09-C1", "evidence/l6_17A6_2026-09-01-10-C2", "evidence/l6_17A6_2026-09-01-11-S"]
FULL_WORDS = 384              # a full-size dense chunk carries 384 words; the 8th chunk of a span carries the remainder


def payload(line: bytes) -> dict | None:
    try:
        return json.loads(base64.urlsafe_b64decode(line.split(b" ")[4] + b"=="))
    except Exception:  # noqa: BLE001 — a corrupted line has no payload
        return None


def chunk_from_prefix(line: bytes) -> int | None:
    """A truncated audit line still carries its JSON head (sorted keys: "chunk" comes
    first): decode the longest whole base64 prefix and read the chunk number from it."""
    import re
    try:
        b64 = line.split(b" ")[4]
        head = base64.urlsafe_b64decode(b64[:len(b64) // 4 * 4][:64])
        m = re.match(rb'\{"chunk":(\d+),', head)
        return int(m.group(1)) if m else None
    except Exception:  # noqa: BLE001
        return None


def line_valid(ln: bytes) -> bool:
    parts = ln.split(b" ")
    body, _, crc = ln.rpartition(b" ")
    return len(parts) == 6 and format(zlib.crc32(body) & 0xFFFFFFFF, "08x").encode() == crc


def audit_words(p: dict) -> list[int] | None:
    """The words a valid audit line carries: dense 1.0.0 (`words`, big-endian) or sparse
    2.0.0 (`entries`: (uint16 pos, uint32 word) pairs over a 384-position window, unlisted
    = zero). Returns the window's words for sparse chunks, all of them for dense."""
    if p.get("schema_version") == "2.0.0":
        import struct
        lo, hi = p["window"]
        words = [0] * (hi - lo)
        raw = base64.urlsafe_b64decode(p["entries"] + "==")
        for i in range(0, len(raw) - len(raw) % 6, 6):
            pos, w = struct.unpack(">HI", raw[i:i + 6])
            if lo <= pos < hi:
                words[pos - lo] = w
        return words
    if "words" in p:
        raw = base64.urlsafe_b64decode(p["words"] + "==")
        return [int.from_bytes(raw[i:i + 4], "big") for i in range(0, len(raw) // 4 * 4, 4)]
    return None


def analyse(d: Path) -> dict:
    raw = (d / "console.log").read_bytes()
    lines = raw.split(b"\n")
    tl = json.loads((d / "timeline.json").read_text())
    out = {"session": d.name, "bytes_received": len(raw), "lines": len(lines),
           "frames_by_type": {}, "valid_by_type": {}, "audit_lines_full_valid": 0, "audit_lines_valid": 0,
           "audit_encoding": None, "audit_words": 0, "audit_zero_words": 0, "loss_events": []}
    normal_len_chunk: dict[int, int] = {}
    valid_len_by_type: dict[str, list[int]] = {}
    for ln in lines:
        if not ln.startswith(b"P3L5 "):
            continue
        parts = ln.split(b" ")
        ty = parts[1].decode() if len(parts) > 1 else "?"
        out["frames_by_type"][ty] = out["frames_by_type"].get(ty, 0) + 1
        if not line_valid(ln):
            continue
        out["valid_by_type"][ty] = out["valid_by_type"].get(ty, 0) + 1
        valid_len_by_type.setdefault(ty, []).append(len(ln))
        if ty != "AUDIT":
            continue
        p = payload(ln)
        if p is None:
            continue
        words = audit_words(p)
        if words is None:
            continue
        out["audit_lines_valid"] += 1
        out["audit_encoding"] = "sparse-v1" if p.get("schema_version") == "2.0.0" else "dense"
        n = len(words)
        # a complete DENSE line = CRC-valid, well-shaped AND a full 384-word chunk (the merged
        # 6002-byte line of C1 #1 is neither, and is not counted here — review 2026-09-01);
        # a sparse chunk always covers its whole window, so every valid sparse line is complete
        if p.get("schema_version") == "2.0.0" or (p.get("word_count") == FULL_WORDS and n == FULL_WORDS):
            out["audit_lines_full_valid"] += 1
        out["audit_words"] += n
        out["audit_zero_words"] += sum(1 for w in words if w == 0)
        normal_len_chunk[p["chunk"]] = max(normal_len_chunk.get(p["chunk"], 0), len(ln))
    # loss events: every CRC-failed or malformed P3L5 line, of any type, with the bytes
    # missing against a normal line of that type (dense audit: the same chunk's longest
    # valid line; other types: the median valid line of the type — REC lines vary a little
    # with the outcome, so that number is approximate and said so)
    # the console's last line is cut where the runner stopped reading (S #1: `SIGNREQ 467`
    # after the epoch end) — a session-end artefact, recorded apart, never a loss event
    last_content = max((i for i, ln in enumerate(lines) if ln), default=-1)
    out["trailing_partial_line"] = None
    for i, ln in enumerate(lines):
        if not ln.startswith(b"P3L5 ") or line_valid(ln):
            continue
        parts = ln.split(b" ")
        if i == last_content:
            out["trailing_partial_line"] = {"line_index": i, "type": parts[1].decode(errors="replace") if len(parts) > 1 else "?",
                                            "line_len": len(ln), "note": "cut at session end by the runner, not a wire loss"}
            continue
        ty = parts[1].decode() if len(parts) > 1 and parts[1].decode(errors="replace").isalpha() else "?"
        seq = parts[2].decode() if len(parts) > 2 and parts[2].isdigit() else "?"
        ev = {"line_index": i, "type": ty, "seq": seq, "line_len": len(ln),
              "kind": "crc-failed line" if len(parts) == 6 else "malformed line (%d fields)" % len(parts)}
        if ty == "AUDIT":
            p = payload(ln)
            chunk = p["chunk"] if p else chunk_from_prefix(ln)
            ev["chunk_claimed"] = chunk
            if len(parts) != 6:
                ev["note"] = "two lines merged: a loss spanning a line boundary (C1 #1: chunk 4's tail and chunk 5's head)"
                ev["bytes_missing_approx"] = 2 * max(normal_len_chunk.values(), default=0) + 1 - len(ln)
            elif chunk is not None and chunk in normal_len_chunk:
                ev["bytes_missing"] = normal_len_chunk[chunk] - len(ln)
        elif ty in valid_len_by_type:
            med = statistics.median(valid_len_by_type[ty])
            ev["bytes_missing_approx"] = int(round(med - len(ln)))
            ev["note"] = f"against the median valid {ty} line of this session ({int(med)} bytes); {ty} lines vary a little with content"
        out["loss_events"].append(ev)
    out["timeline"] = {"crc_dropped": tl["crc_dropped"], "bad_frames": tl["bad_frames"],
                       "crc_dropped_by_type": tl.get("crc_dropped_by_type", {})}
    log = json.loads((d / "run_log.json").read_text())
    audited = [r for r in log["loop_records"] if r["outcome"] != "REFUSED_BY_GATE"]
    # transmission opportunities for the push era: every full-size dense chunk the board
    # SENT, valid or not (a merged line = two); for the pull era every AUDIT line on the wire
    if out["audit_encoding"] == "dense" or out["audit_encoding"] is None:
        sent_full = sum((2 if len(ln) > 4000 else 1) for ln in lines if ln.startswith(b"P3L5 AUDIT") and len(ln) >= 2700)
    else:
        sent_full = out["frames_by_type"].get("AUDIT", 0)
    out["full_size_chunks_on_wire"] = sent_full
    out["records_with_audit"] = len(audited)
    out["records"] = len(log["loop_records"])
    out["audit_zero_fraction"] = (out["audit_zero_words"] / out["audit_words"]) if out["audit_words"] else None
    out["epoch_end"] = log["session_summary"]["epoch_end"]["kind"]
    return out


def main() -> int:
    per = [analyse(R / s) for s in SESSIONS]
    total = {"sessions": len(per), "bytes_received": sum(p["bytes_received"] for p in per),
             "frames": sum(sum(p["frames_by_type"].values()) for p in per),
             "audit_frames": sum(p["frames_by_type"].get("AUDIT", 0) for p in per),
             "rec_frames": sum(p["frames_by_type"].get("REC", 0) for p in per),
             "audit_lines_valid": sum(p["audit_lines_valid"] for p in per),
             "audit_lines_full_valid": sum(p["audit_lines_full_valid"] for p in per),
             "full_size_chunks_on_wire": sum(p["full_size_chunks_on_wire"] for p in per),
             "loss_events": sum(len(p["loss_events"]) for p in per),
             "loss_events_by_type": {},
             "audit_words": sum(p["audit_words"] for p in per),
             "audit_zero_words": sum(p["audit_zero_words"] for p in per)}
    for p in per:
        for ev in p["loss_events"]:
            total["loss_events_by_type"][ev["type"]] = total["loss_events_by_type"].get(ev["type"], 0) + 1
    total["audit_zero_fraction"] = total["audit_zero_words"] / total["audit_words"] if total["audit_words"] else None
    total["loss_events_per_MB"] = total["loss_events"] / (total["bytes_received"] / 1e6) if total["bytes_received"] else None
    total["loss_events_per_frame"] = total["loss_events"] / total["frames"] if total["frames"] else None
    push = [p for p in per if p["audit_encoding"] == "dense" or p["audit_encoding"] is None]
    pull = [p for p in per if p["audit_encoding"] == "sparse-v1"]
    total["by_era"] = {
        "push (C1 #1–#3, v0.2)": {"bytes": sum(p["bytes_received"] for p in push), "events": sum(len(p["loss_events"]) for p in push),
                                  "full_size_audit_chunks_on_wire": sum(p["full_size_chunks_on_wire"] for p in push)},
        "pull-v2 (C1 #4, C2 #1, S #1, v0.3)": {"bytes": sum(p["bytes_received"] for p in pull), "events": sum(len(p["loss_events"]) for p in pull),
                                                "audit_lines_on_wire": sum(p["full_size_chunks_on_wire"] for p in pull)}}
    rep = {"schema": "l6_console_loss_stats", "schema_version": "2.0.0", "sessions": per, "total": total,
           "caveat": "exposure and events only. Six sessions: three push-era C1 sessions (one read nothing) and three pull-v2 "
                     "sessions. Four loss events in all: three inside full-size (384-word) push-era audit lines (C1 #1 one "
                     "boundary merge, C1 #3 two interior deletions), one inside a pull-era REC line (S #1, interior deletion). "
                     "No position-specific inference; no cause is named — the path is CH340 → usbipd → WSL vhci_hcd without "
                     "flow control, and nothing here measures it. 'full_size_chunks_on_wire' counts push-era full-size dense "
                     "audit lines (a merged line = two) and, for pull-v2 sessions, every AUDIT line on the wire; "
                     "bytes_missing_approx for non-audit lines is against the session's median valid line of that type"}
    out = R / "evidence/l6_console_loss_stats.json"
    out.write_text(json.dumps(rep, indent=2) + "\n")
    print(json.dumps(total, indent=1))
    for p in per:
        print(p["session"], "bytes", p["bytes_received"], "frames", sum(p["frames_by_type"].values()), "audit", p["frames_by_type"].get("AUDIT", 0),
              p["audit_encoding"], "zero", None if p["audit_zero_fraction"] is None else round(p["audit_zero_fraction"], 4),
              "events", [(e["type"], e["seq"], e.get("bytes_missing", e.get("bytes_missing_approx"))) for e in p["loss_events"]])
    return 0


if __name__ == "__main__":
    sys.exit(main())
