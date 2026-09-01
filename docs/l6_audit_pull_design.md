# L6 next protocol: host-paced audit pull with lossless sparse words (design, host-only)

> **Standing: PROPOSAL, modelled on the host only** (`host/l6_audit_pull.py`,
> `tests/test_l6_audit_pull.py`). Authorised as item 3 of the owner's design review of
> 2026-09-01 after the byte-loss stop-loss. No firmware, no image, no preregistration
> change, no ruling, no board. Whether it is adopted, and the new firmware/image and
> prereg version that would follow, are the owner's next ruling.

## 1. What it has to fix

Three contiguous byte deletions in 2.33 MB of console traffic (`docs/l6_console_loss_summary.md`):
0.48 % of complete audit lines, all inside the ~24 KB audit burst each candidate pushes
after link 3, on a CH340 → usbipd → WSL path with no flow control. Under the push
protocol a lost chunk cannot be asked for again, so it is a HOLD; and 96.4 % of the
words pushed are zero. C1/C2 stay all-self-reporting (the owner ruled against passing by
sampling less), so the audit must become both **recoverable** and **small** without
becoming weaker.

## 2. The protocol

Same `P3L5` framing, same token, same CRC. New types are proposals.

| direction | frame | payload | when |
|---|---|---|---|
| board → host | `AUDIT_READY` | `seq, span, total_words, chunks, nonzero` | after link 3 (span `streams+readback`) or at a link-2 refusal (span `streams`), before the record |
| host → board | `AUDITGET` | `seq, chunk` | once per chunk, again on a failed attempt (≤ `MAX_RETRIES` = 2 retries) |
| board → host | `AUDIT` | `seq, chunk, chunks, span, total_words, window [lo, hi), encoding "sparse-v1", entries` | in answer to each `AUDITGET`; served as often as asked |
| host → board | `AUDITDONE` | `seq` | when every chunk verified |
| board → host | `REC` | as today; `verified: audited` iff `AUDITDONE` arrived | |

**Chunk** = a fixed window of `WINDOW` = 384 word positions of the full span (8 chunks
for 2814 words, as today). **Entries** = the non-zero words of the window as packed
`(uint16 position, uint32 word)` pairs, positions absolute in the span, **strictly
ascending and unique**, base64url. **An unlisted position is zero by definition.** The
host rebuilds all `total_words` words and recomputes the three hashes with the existing
`validators.audit.recompute` — the audit's content and the falsifier are unchanged.

Strictness on the host (each a refusal): alphabet, whole 6-byte pairs, position inside
the window, ascending and unique, no listed zero, chunks exactly `0..n-1`, a chunk served
twice with different content. A chunk that verifies but whose rebuilt words do not
recompute the record's hashes is `Falsified` — exactly as now.

## 3. Loss handling, budgeted

A chunk whose line fails CRC, is malformed, or does not arrive within `CHUNK_TIMEOUT` is
asked for again, at most twice more. **Every failed attempt is kept verbatim in the
ledger** (`Ledger.lines_kept`) and a CRC-failed attempt counts against the D-s4 budget —
the same one inbound ledger `host/l6_console.py` now enforces for every frame type; a
malformed line and a timeout are attempts but not CRC drops. Retries exhausted on any
chunk → the audit is incomplete → HOLD, as now. The budget can end the epoch `PROTOCOL`
mid-pull, as now.

## 4. What the model proves (host-only)

On C1 #3's real seq-1 words (2814 words, 87 non-zero):

- the sparse encoding is lossless and recomputes the record's `staged_stream_sha256`,
  `staged_sha256` and `readback_sha256`;
- the wire cost per candidate falls from **22 320 B / 1.94 s to 4 282 B / 0.37 s** (19 %),
  including `AUDIT_READY`, eight `AUDITGET`s and `AUDITDONE`;
- **C1 #3's losses** (309 and 229 bytes inside chunk 3) and **C1 #1's** (39 bytes across
  the chunk 4/5 boundary, merging the lines) are each recovered by one retry, with the
  failed attempt in the ledger and one CRC drop counted;
- three failed attempts on one chunk → `RecordError` (HOLD), never a pass;
- three drops across chunks with a budget of 2 → `PROTOCOL_CRC_BUDGET: 3 > 2`;
- a timeout is an attempt, not a CRC drop;
- a chunk with a valid CRC but one wrong word → `Falsified` on recompute;
- the ledger's bytes include every retransmission, so a rate report under this protocol
  carries its own retransmission cost.

## 5. Rate and breakdown under the new protocol

The `audit` stage becomes `AUDIT_READY` → `AUDITDONE` on the host clock, including every
retry; `period` and the CoV are unchanged in definition. On C1 #3's numbers the audit
stage would fall from 1.85 s to ≈ 0.4 s of a ≈ 0.8 s period, i.e. from 76 % of the link to
roughly half, and the bytes exposed to a deletion per candidate from 24 KB to 4 KB.

## 6. What adopting it would take (not done here)

Firmware (`p3_app.c`, `p3_wire.c`): serve chunks on `AUDITGET` from the buffers that
already hold the words (they persist until the record is emitted); the sparse serialiser;
`AUDIT_READY`/`AUDITDONE`; `verified` from `AUDITDONE`. Host: the pull loop in the console
session, the sparse assembler in `validators/audit.py` (2.0.0 chunks alongside 1.0.0),
the contract test through the C wire twin, the L6 checks' expected-frame brackets
(`AUDIT` count is no longer fixed at 8 per audited record; the D-s4 formula needs the
new brackets). Preregistration: a new version (new hash, new freeze) for §3a's wording,
D-s4's brackets and §4.7. Then §2-style compatibility review, two byte-identical builds,
new rulings. The image `bd1454cd…` stays the historical image that completed a board
epoch; it is not defective.

## 7. Alternatives considered

Smaller chunks alone: the bytes do not shrink and any missing chunk is still a HOLD.
Sampled C1/C2: weakens the calibration's purpose (owner). A different console path
(direct FTDI/CP210x, hardware flow control): kept as the fallback; an instrument change
with its own identity gate.
