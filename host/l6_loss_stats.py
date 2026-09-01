#!/usr/bin/env python3
"""Console byte-loss statistics over the L6 sessions (design review 2026-09-01, item 2).

Counts, per session and in total: frames received by type, full-length audit lines
(the ~3 KB ones), bytes received, loss events (each with seq, chunk, position and the
number of bytes missing), and the fraction of zero words in the audit payloads. Written
so the denominators are explicit; it draws no chunk-specific conclusion from two of
three events landing on chunk 3 — with three events, a position is not a pattern.
"""
from __future__ import annotations

import base64
import json
import sys
import zlib
from pathlib import Path

R = Path(__file__).resolve().parent.parent
SESSIONS = ["evidence/l6_17A6_2026-09-01-06-C1", "evidence/l6_17A6_2026-09-01-07-C1", "evidence/l6_17A6_2026-09-01-08-C1"]
FULL_LINE_MIN = 2900          # a complete 384-word audit chunk line is 3015–3020 bytes


def payload(line: bytes) -> dict | None:
    try:
        return json.loads(base64.urlsafe_b64decode(line.split(b" ")[4] + b"=="))
    except Exception:  # noqa: BLE001 — a corrupted line has no payload
        return None


def chunk_from_prefix(line: bytes) -> int | None:
    """A truncated line still carries its JSON head (sorted keys: "chunk" comes first): decode
    the longest whole base64 prefix and read the chunk number from it."""
    import re
    try:
        b64 = line.split(b" ")[4]
        head = base64.urlsafe_b64decode(b64[:len(b64) // 4 * 4][:64])
        m = re.match(rb'\{"chunk":(\d+),', head)
        return int(m.group(1)) if m else None
    except Exception:  # noqa: BLE001
        return None


def analyse(d: Path) -> dict:
    raw = (d / "console.log").read_bytes()
    lines = raw.split(b"\n")
    tl = json.loads((d / "timeline.json").read_text())
    out = {"session": d.name, "bytes_received": len(raw), "lines": len(lines),
           "frames_by_type": {}, "audit_lines_full": 0, "audit_words": 0, "audit_zero_words": 0, "loss_events": []}
    normal_len = {}
    for ln in lines:
        if not ln.startswith(b"P3L5 "):
            continue
        parts = ln.split(b" ")
        ty = parts[1].decode() if len(parts) > 1 else "?"
        out["frames_by_type"][ty] = out["frames_by_type"].get(ty, 0) + 1
        if ty != "AUDIT":
            continue
        if len(ln) >= FULL_LINE_MIN:
            out["audit_lines_full"] += 1
        body, _, crc = ln.rpartition(b" ")
        ok = format(zlib.crc32(body) & 0xFFFFFFFF, "08x").encode() == crc and len(parts) == 6
        p = payload(ln) if ok else None
        if p is not None:
            words = base64.urlsafe_b64decode(p["words"] + "==")
            n = len(words) // 4
            out["audit_words"] += n
            out["audit_zero_words"] += sum(1 for i in range(n) if words[4 * i:4 * i + 4] == b"\0\0\0\0")
            normal_len[p["chunk"]] = max(normal_len.get(p["chunk"], 0), len(ln))
    # loss events: CRC-failed or malformed AUDIT lines, with the bytes missing vs a normal line of that chunk
    for i, ln in enumerate(lines):
        if not ln.startswith(b"P3L5 AUDIT"):
            continue
        parts = ln.split(b" ")
        body, _, crc = ln.rpartition(b" ")
        ok = len(parts) == 6 and format(zlib.crc32(body) & 0xFFFFFFFF, "08x").encode() == crc
        if ok:
            continue
        seq = parts[2].decode() if len(parts) > 2 else "?"
        p = payload(ln)
        chunk = p["chunk"] if p else chunk_from_prefix(ln)
        ev = {"line_index": i, "seq": seq, "chunk_claimed": chunk, "line_len": len(ln),
              "kind": "crc-failed line" if len(parts) == 6 else "malformed line (%d fields)" % len(parts)}
        if len(parts) != 6:
            ev["note"] = "two lines merged: a loss spanning a line boundary (C1 #1: chunk 4's tail and chunk 5's head)"
            ev["bytes_missing_approx"] = 2 * max(normal_len.values(), default=0) + 1 - len(ln)
        elif chunk is not None and chunk in normal_len:
            ev["bytes_missing"] = normal_len[chunk] - len(ln)
        out["loss_events"].append(ev)
    out["timeline"] = {"crc_dropped": tl["crc_dropped"], "bad_frames": tl["bad_frames"]}
    out["audit_zero_fraction"] = (out["audit_zero_words"] / out["audit_words"]) if out["audit_words"] else None
    return out


def main() -> int:
    per = [analyse(R / s) for s in SESSIONS]
    total = {"bytes_received": sum(p["bytes_received"] for p in per),
             "audit_frames": sum(p["frames_by_type"].get("AUDIT", 0) for p in per),
             "audit_lines_full": sum(p["audit_lines_full"] for p in per),
             "loss_events": sum(len(p["loss_events"]) for p in per),
             "audit_words": sum(p["audit_words"] for p in per),
             "audit_zero_words": sum(p["audit_zero_words"] for p in per)}
    total["audit_zero_fraction"] = total["audit_zero_words"] / total["audit_words"] if total["audit_words"] else None
    total["loss_events_per_full_audit_line"] = total["loss_events"] / total["audit_lines_full"] if total["audit_lines_full"] else None
    total["loss_events_per_MB"] = total["loss_events"] / (total["bytes_received"] / 1e6) if total["bytes_received"] else None
    rep = {"schema": "l6_console_loss_stats", "schema_version": "1.0.0", "sessions": per, "total": total,
           "caveat": "three events in three sessions: no position-specific inference (two on chunk 3 is not a chunk-3 fault); "
                     "all three fell inside complete ~3 KB audit lines; C1 #2 read nothing and contributes no bytes"}
    out = R / "evidence/l6_console_loss_stats.json"
    out.write_text(json.dumps(rep, indent=2) + "\n")
    print(json.dumps(total, indent=1))
    for p in per:
        print(p["session"], "bytes", p["bytes_received"], "audit", p["frames_by_type"].get("AUDIT", 0), "full", p["audit_lines_full"],
              "zero", None if p["audit_zero_fraction"] is None else round(p["audit_zero_fraction"], 4), "events", p["loss_events"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
