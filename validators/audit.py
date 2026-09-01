"""The audit gate: raw words served by the application, reassembled and recomputed on the
host, compared with the compact record that claimed them.

WHY THIS FILE EXISTS. Until the design review of 2026-09-01 the runner wrote the served
chunks to `audits.json` and then checked only that every self-reporting record carried
`"verified": "audited"` -- the application's OWN mark. Nothing reassembled the words or
recomputed a single hash, so an application that served any bytes at all and marked its
records audited could have been reported PASS. That contradicted the preregistration's
own falsifier ("an audited candidate's raw words do not recompute the hashes its compact
record claimed") and left it unenforced. Sessions 1 and 3 were recomputed by hand,
afterwards; that is evidence, not a gate.

This module is the gate. `validate_standalone_run_log` calls it and DERIVES every record's
mark from what was verified here; the application's mark must agree or the log is refused.

  * `assemble`  -- closed reassembly per seq: schema, span, chunk numbering, offsets,
                   counts, total, alphabet; anything missing, duplicated, overlapping,
                   gapped, over-long, mis-spanned or mixed across seqs is a RecordError.
  * `recompute` -- the three hash domains from the words alone (fabricmap's `run_log`
                   domains via p3_gate: sequence over the streams' words, frames_hash over
                   the parsed staged frames, frames_hash over the readback frames). Past
                   `assemble`, a failure is about CONTENT: words that do not parse as a
                   staging, a repeated envelope — `Falsified`. The manifest's own envelope
                   contract is checked first and is host-side: RecordError.
  * `verify`    -- per record: which hashes the words back, and whether they agree with
                   `evidence.app_oracle_record` (or, for STOP_LINK2, with the refusal's own
                   claim). Disagreement is `Falsified`. A short audit ("streams") behind a
                   record that claims a readback backs nothing about link 3, so the host
                   derives `replayed-only` for it, whatever the application wrote.
"""
from __future__ import annotations

import base64
import hashlib
import sys
from pathlib import Path

from .records import Falsified, RecordError, self_report_class

STREAM_WORDS = 534
ENVELOPES = 3
FRAME_WORDS = 101
TARGET_FRAMES = 12
STREAM_SPAN = ENVELOPES * STREAM_WORDS                     # 1602
SPAN_WORDS = {"streams": STREAM_SPAN,                       # a link-2 refusal: no readback exists
              "streams+readback": STREAM_SPAN + TARGET_FRAMES * FRAME_WORDS}   # 2814
CHUNK_KEYS = ("schema", "schema_version", "seq", "span", "chunk", "chunks", "word_offset",
              "word_count", "total_words", "words")
# app_audit_chunk 2.0.0 — the host-paced sparse pull (docs/l6_audit_pull_design.md): a chunk
# is a fixed WINDOW of positions; `entries` lists the NON-ZERO words of that window as packed
# (uint16 position, uint32 word) pairs, positions absolute in the span, strictly ascending
# and unique; an unlisted position is zero by definition. Lossless: the host rebuilds every
# word and the three hash domains are recomputed exactly as for a dense chunk set.
SPARSE_WINDOW = 384
SPARSE_ENCODING = "sparse-v1"
SPARSE_KEYS = ("schema", "schema_version", "encoding", "seq", "span", "chunk", "chunks", "total_words",
               "window", "entries")
_B64 = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")


def _gate():
    """p3_gate lives in host/; fabricmap's run_log beneath it. Imported lazily so the
    validators package stays importable on its own."""
    r = Path(__file__).resolve().parent.parent
    for p in (r / "host", r):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    import p3_gate as g  # noqa: E402
    import run_log as rl  # noqa: E402
    return g, rl


def _decode_words(b64: str, where: str) -> list[int]:
    if not isinstance(b64, str) or not b64:
        raise RecordError(f"{where}: words must be a non-empty base64url string")
    body = b64.rstrip("=")
    bad = set(body) - _B64
    if bad:
        raise RecordError(f"{where}: words contain characters outside base64url: {sorted(bad)}")
    try:
        raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
    except Exception as exc:  # noqa: BLE001 — any decode failure is one finding
        raise RecordError(f"{where}: words do not decode: {exc}") from None
    if len(raw) % 4:
        raise RecordError(f"{where}: decoded bytes ({len(raw)}) are not whole 32-bit words")
    return [int.from_bytes(raw[i:i + 4], "big") for i in range(0, len(raw), 4)]


def sparse_chunk_count(total_words: int) -> int:
    return (total_words + SPARSE_WINDOW - 1) // SPARSE_WINDOW


def sparse_window(chunk: int, total_words: int) -> tuple[int, int]:
    return chunk * SPARSE_WINDOW, min((chunk + 1) * SPARSE_WINDOW, total_words)


def decode_entries(b64: str, window_start: int, window_end: int) -> list[tuple[int, int]]:
    """Strict: base64url alphabet, whole 6-byte pairs, positions inside the window, strictly
    ascending and unique, no listed zero. An accepted chunk means exactly one set of words."""
    import struct
    if not isinstance(b64, str):
        raise RecordError("sparse entries must be a string")
    body = b64.rstrip("=")
    bad = set(body) - _B64
    if bad:
        raise RecordError(f"sparse entries: characters outside base64url: {sorted(bad)}")
    try:
        raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
    except Exception as exc:  # noqa: BLE001
        raise RecordError(f"sparse entries do not decode: {exc}") from None
    if len(raw) % 6:
        raise RecordError(f"sparse entries: {len(raw)} bytes are not whole (uint16, uint32) pairs")
    entries = [struct.unpack(">HI", raw[i:i + 6]) for i in range(0, len(raw), 6)]
    last = -1
    for pos, word in entries:
        if not window_start <= pos < window_end:
            raise RecordError(f"sparse entries: position {pos} outside the chunk window [{window_start}, {window_end})")
        if pos <= last:
            raise RecordError(f"sparse entries: position {pos} not strictly ascending after {last} (duplicate or disorder)")
        if word == 0:
            raise RecordError(f"sparse entries: position {pos} lists a zero word (unlisted means zero)")
        last = pos
    return entries


def encode_entries(words: list[int], window_start: int, window_end: int) -> str:
    """The reference encoder (the firmware's twin): the non-zero words of one window."""
    import struct
    out = bytearray()
    for pos in range(window_start, min(window_end, len(words))):
        if words[pos]:
            out += struct.pack(">HI", pos, words[pos] & 0xFFFFFFFF)
    return base64.urlsafe_b64encode(bytes(out)).decode()


def build_sparse_chunk(seq: int, chunk: int, span: str, words: list[int]) -> dict:
    total = SPAN_WORDS[span]
    if len(words) != total:
        raise ValueError(f"{len(words)} words for span {span!r}")
    lo, hi = sparse_window(chunk, total)
    return {"schema": "app_audit_chunk", "schema_version": "2.0.0", "encoding": SPARSE_ENCODING, "seq": seq,
            "chunk": chunk, "chunks": sparse_chunk_count(total), "span": span, "total_words": total,
            "window": [lo, hi], "entries": encode_entries(words, lo, hi)}


def check_sparse_chunk(c: dict, where: str = "audit chunk") -> None:
    """One 2.0.0 chunk's own shape: keys, versions, pinned span/total, chunk range, exact
    window, strict entries. Completeness across a seq is `_assemble_sparse`'s question."""
    if not isinstance(c, dict):
        raise RecordError(f"{where}: not an object")
    missing = [k for k in SPARSE_KEYS if k not in c]
    if missing:
        raise RecordError(f"{where}: missing {missing}")
    if c["schema"] != "app_audit_chunk" or c["schema_version"] != "2.0.0" or c["encoding"] != SPARSE_ENCODING:
        raise RecordError(f"{where}: not an app_audit_chunk 2.0.0 {SPARSE_ENCODING} chunk")
    for k in ("seq", "chunk", "chunks", "total_words"):
        if not isinstance(c[k], int) or isinstance(c[k], bool) or c[k] < 0:
            raise RecordError(f"{where}: {k} must be a non-negative integer")
    if c["span"] not in SPAN_WORDS or c["total_words"] != SPAN_WORDS[c["span"]]:
        raise RecordError(f"{where}: span {c['span']!r} / total_words {c['total_words']} not the pinned pair")
    if c["chunks"] != sparse_chunk_count(c["total_words"]):
        raise RecordError(f"{where}: chunks {c['chunks']} != {sparse_chunk_count(c['total_words'])} for {c['total_words']} words")
    if not 0 <= c["chunk"] < c["chunks"]:
        raise RecordError(f"{where}: chunk {c['chunk']} out of range 0..{c['chunks'] - 1}")
    if list(c["window"]) != list(sparse_window(c["chunk"], c["total_words"])):
        raise RecordError(f"{where}: window {c['window']} is not {list(sparse_window(c['chunk'], c['total_words']))}")
    decode_entries(c["entries"], *sparse_window(c["chunk"], c["total_words"]))


def _assemble_sparse(chunks: list[dict]) -> dict[int, dict]:
    """Closed reassembly of 2.0.0 chunks: every chunk 0..n-1 exactly once (a byte-identical
    duplicate is a retry's echo and is fine; a different one is refused), every chunk of a
    seq bound to ONE span/total_words/chunks, windows exact, entries strict."""
    by_seq: dict[int, dict[int, dict]] = {}
    for i, c in enumerate(chunks):
        where = f"audit chunk #{i}"
        check_sparse_chunk(c, where)
        group = by_seq.setdefault(c["seq"], {})
        first = next(iter(group.values()), None)
        if first is not None and (first["span"], first["total_words"], first["chunks"]) != (c["span"], c["total_words"], c["chunks"]):
            raise RecordError(f"audit seq {c['seq']}: chunk {c['chunk']} names span/total/chunks "
                              f"{(c['span'], c['total_words'], c['chunks'])}, the seq's first chunk names "
                              f"{(first['span'], first['total_words'], first['chunks'])} — one transaction, one binding")
        prev = group.get(c["chunk"])
        if prev is not None and prev != c:
            raise RecordError(f"audit seq {c['seq']}: chunk {c['chunk']} served twice with different content")
        group[c["chunk"]] = c
    out = {}
    for seq, got in sorted(by_seq.items()):
        first = next(iter(got.values()))
        want = set(range(first["chunks"]))
        if set(got) != want:
            raise RecordError(f"audit seq {seq}: chunk numbers must be exactly 0..{first['chunks'] - 1}: "
                              f"missing {sorted(want - set(got))}, out of range {sorted(set(got) - want)}")
        words = [0] * first["total_words"]
        for ch in sorted(got):
            lo, hi = got[ch]["window"]
            for pos, w in decode_entries(got[ch]["entries"], lo, hi):
                words[pos] = w
        out[seq] = {"span": first["span"], "words": words, "chunks": first["chunks"], "encoding": SPARSE_ENCODING}
    return out


def assemble(chunks: list[dict]) -> dict[int, dict]:
    """Closed reassembly: returns {seq: {"span", "words", "chunks"}} or raises RecordError
    naming the first defect. Order of arrival is irrelevant; chunk NUMBERS are not. Dense
    1.0.0 chunks and sparse 2.0.0 chunks may not be mixed within one seq; each seq's chunks
    are assembled by their own version's rules."""
    sparse = [c for c in chunks if isinstance(c, dict) and c.get("schema_version") == "2.0.0"]
    plain = [c for c in chunks if not (isinstance(c, dict) and c.get("schema_version") == "2.0.0")]
    out = _assemble_dense(plain) if plain else {}
    if sparse:
        got = _assemble_sparse(sparse)
        for seq in got:
            if seq in out:
                raise RecordError(f"audit seq {seq}: dense and sparse chunks mixed in one seq")
        out.update(got)
    return out


def _assemble_dense(chunks: list[dict]) -> dict[int, dict]:
    by_seq: dict[int, list[dict]] = {}
    for i, c in enumerate(chunks):
        where = f"audit chunk #{i}"
        if not isinstance(c, dict):
            raise RecordError(f"{where}: not an object")
        missing = [k for k in CHUNK_KEYS if k not in c]
        if missing:
            raise RecordError(f"{where}: missing {missing}")
        if c["schema"] != "app_audit_chunk" or c["schema_version"] != "1.0.0":
            raise RecordError(f"{where}: schema {c['schema']!r}/{c['schema_version']!r} is not app_audit_chunk/1.0.0")
        for k in ("seq", "chunk", "chunks", "word_offset", "word_count", "total_words"):
            if not isinstance(c[k], int) or isinstance(c[k], bool) or c[k] < 0:
                raise RecordError(f"{where}: {k} must be a non-negative integer")
        if c["span"] not in SPAN_WORDS:
            raise RecordError(f"{where}: span {c['span']!r} is not one of {sorted(SPAN_WORDS)}")
        by_seq.setdefault(c["seq"], []).append(c)
    out: dict[int, dict] = {}
    for seq, group in sorted(by_seq.items()):
        where = f"audit seq {seq}"
        spans = {c["span"] for c in group}
        counts = {c["chunks"] for c in group}
        totals = {c["total_words"] for c in group}
        if len(spans) != 1 or len(counts) != 1 or len(totals) != 1:
            raise RecordError(f"{where}: chunks disagree on span/chunks/total_words "
                              f"({sorted(spans)}, {sorted(counts)}, {sorted(totals)})")
        span, n_chunks, total = spans.pop(), counts.pop(), totals.pop()
        if total != SPAN_WORDS[span]:
            raise RecordError(f"{where}: total_words {total} is not the pinned {SPAN_WORDS[span]} for span {span!r}")
        if n_chunks < 1:
            raise RecordError(f"{where}: chunks must be >= 1")
        numbers = sorted(c["chunk"] for c in group)
        if len(set(numbers)) != len(numbers):
            dup = sorted({x for x in numbers if numbers.count(x) > 1})
            raise RecordError(f"{where}: duplicate chunk numbers {dup}")
        if numbers != list(range(n_chunks)):
            missing = sorted(set(range(n_chunks)) - set(numbers))
            extra = sorted(set(numbers) - set(range(n_chunks)))
            raise RecordError(f"{where}: chunk numbers must be exactly 0..{n_chunks - 1}: "
                              f"missing {missing}, out of range {extra}")
        words: list[int] = []
        for c in sorted(group, key=lambda c: c["chunk"]):
            cw = f"{where} chunk {c['chunk']}"
            if c["word_offset"] != len(words):
                raise RecordError(f"{cw}: word_offset {c['word_offset']} but {len(words)} words precede it "
                                  f"({'overlap' if c['word_offset'] < len(words) else 'gap'})")
            decoded = _decode_words(c["words"], cw)
            if len(decoded) != c["word_count"]:
                raise RecordError(f"{cw}: word_count {c['word_count']} but {len(decoded)} words decoded")
            if c["word_count"] == 0:
                raise RecordError(f"{cw}: empty chunk")
            words += decoded
            if len(words) > total:
                raise RecordError(f"{cw}: {len(words)} words exceed total_words {total}")
        if len(words) != total:
            raise RecordError(f"{where}: {len(words)} words reassembled, total_words says {total}")
        out[seq] = {"span": span, "words": words, "chunks": n_chunks}
    return out


def _envelope_contract(g, manifest: dict) -> list[dict]:
    """The manifest-derived envelope contract the recompute rests on, checked BEFORE any
    served word is interpreted (design review round 3, 2026-09-01): exactly three unique
    envelope FAR sets, exactly four target frames each, twelve unique target FARs in all,
    and those twelve equal to the pinned frame roles' targets. A manifest that fails this,
    or that cannot be parsed, is a HOST-side defect — RecordError, never a falsifier: the
    board served nothing wrong. With this contract holding, three parseable streams with
    three distinct envelopes necessarily stage twelve frames, so "fewer than twelve" past
    this point can only be a host implementation invariant failure, also RecordError."""
    try:
        envs = g.envelopes(manifest)
        base, roles = g.gc.pinned_frames(manifest)
        # shape before content: a row missing far_set/targets, or targets that are not a
        # list of ints, is the same host-side finding, not a stray KeyError/TypeError
        # (round-4 review's non-blocking note)
        if not isinstance(envs, list) or not all(isinstance(e, dict) for e in envs):
            raise RecordError("envelope table is not a list of rows")
        for e in envs:
            if "far_set" not in e or "targets" not in e:
                raise RecordError(f"envelope row missing far_set/targets: {sorted(e)}")
            if not isinstance(e["far_set"], int) or not isinstance(e["targets"], list) \
                    or not all(isinstance(f, int) for f in e["targets"]):
                raise RecordError(f"envelope {e.get('far_set')!r}: far_set must be an int and targets a list of ints")
        if not isinstance(roles, dict):
            raise RecordError("pinned frame roles are not a mapping")
    except RecordError as exc:
        raise RecordError(f"invalid manifest: {exc}") from None
    except Exception as exc:  # noqa: BLE001 — any manifest parse failure is one finding
        raise RecordError(f"invalid manifest: the envelope table cannot be read: {type(exc).__name__}: {exc}") from None
    far_sets = [e["far_set"] for e in envs]
    if len(envs) != ENVELOPES or len(set(far_sets)) != ENVELOPES:
        raise RecordError(f"invalid manifest: {len(envs)} envelopes with far_sets {sorted(map(hex, far_sets))}, "
                          f"contract is exactly {ENVELOPES} unique")
    # The clauses overlap by construction (three envelopes × four each = twelve, and twelve
    # unique equal to the pinned roles), so each one is ordered to be the FIRST to see its
    # own defect and its message names that defect; the tests assert the message, which is
    # how a removed clause is detected even though another would eventually refuse too.
    targets = [f for e in envs for f in e["targets"]]
    if len(targets) != TARGET_FRAMES or len(set(targets)) != TARGET_FRAMES:
        raise RecordError(f"invalid manifest: {len(targets)} target FARs ({len(set(targets))} unique), "
                          f"contract is exactly {TARGET_FRAMES} unique")
    bad = [hex(e["far_set"]) for e in envs if len(e["targets"]) != TARGET_FRAMES // ENVELOPES]
    if bad:
        raise RecordError(f"invalid manifest: envelopes {bad} do not stage exactly "
                          f"{TARGET_FRAMES // ENVELOPES} target frames each")
    pinned = {f for f, r in roles.items() if r == "target"}
    if set(targets) != pinned:
        raise RecordError("invalid manifest: the envelope table's target FARs are not the pinned target roles")
    return envs


def recompute(words: list[int], span: str, manifest: dict) -> dict:
    """The hash domains the words support.

    THE CLASSIFICATION BOUNDARY (design review round 2, 2026-09-01). This function is
    reached only after `assemble()` accepted the chunk stream: the transport and accounting
    layer is already clean. Everything that fails from here on is about the CONTENT the
    application served — raw words that are not a staging the gate grammar describes, that
    name the same envelope twice, or that do not stage all twelve target frames — and so
    cannot support the hashes the record claimed. That is prereg §3's "audited raw words do
    not recompute the compact record": `Falsified`, a KILL, never an instrument HOLD.
    Two things stay RecordError because they are the HOST's, not the board's: the
    manifest-derived envelope contract (`_envelope_contract`, checked first) and a
    caller-contract word count; a missing manifest is refused in `verify()` before we get
    here. With the contract holding, "fewer than twelve frames" cannot be produced by
    served content and is a host invariant failure — RecordError (round 3)."""
    g, rl = _gate()
    envs = _envelope_contract(g, manifest)          # host side first: RecordError territory
    if len(words) != SPAN_WORDS[span]:
        raise RecordError(f"recompute: {len(words)} words for span {span!r} (caller contract; assemble() enforces the span)")
    streams = [words[i * STREAM_WORDS:(i + 1) * STREAM_WORDS] for i in range(ENVELOPES)]
    out = {"staged_stream_sha256": hashlib.sha256(
        b"".join(w.to_bytes(4, "big") for s in streams for w in s)).hexdigest()}
    far_sets = {e["far_set"] for e in envs}
    staged: dict[int, list[int]] = {}
    seen = []
    for k, s in enumerate(streams):
        try:
            far, frames5 = g.parse_stream(s, far_sets)
        except ValueError as exc:
            raise Falsified(f"served raw words: audit stream {k} does not parse as a staging "
                            f"({exc}) — the words cannot support the record's staged hashes "
                            f"(prereg §3: audited words do not recompute the compact record)") from None
        if far in seen:
            raise Falsified(f"served raw words: audit stream {k} repeats envelope {far:#x}, so the "
                            f"streams do not stage the twelve target frames the record claims (prereg §3)")
        seen.append(far)
        env = next(e for e in envs if e["far_set"] == far)
        for i, f in enumerate(env["targets"]):
            staged[f] = frames5[i]
    if len(staged) != TARGET_FRAMES:
        # unreachable while the envelope contract holds (three distinct parseable envelopes
        # × four targets = twelve): a host implementation invariant, not something the board
        # can make happen — so RecordError, deliberately not Falsified (round 3)
        raise RecordError(f"host invariant: {len(staged)} target frames staged under a valid envelope "
                          f"contract, not {TARGET_FRAMES}")
    out["staged_sha256"] = rl.frames_hash(staged)
    if span == "streams+readback":
        base, roles = g.gc.pinned_frames(manifest)
        targets = sorted(f for f, r in roles.items() if r == "target")
        tail = words[STREAM_SPAN:]
        read = {far: tail[i * FRAME_WORDS:(i + 1) * FRAME_WORDS] for i, far in enumerate(targets)}
        out["readback_sha256"] = rl.frames_hash(read)
    else:
        out["readback_sha256"] = None
    return out


def verify(log: dict, chunks: list[dict], manifest: dict | None) -> tuple[dict[int, str], dict[int, dict]]:
    """Host-derived marks for every loop record, and the per-seq verification detail.

    marks[seq] is "audited" only when words were served for seq AND every hash the record
    claims that the words can support recomputes to the record's value. A mismatch is a
    Falsified (prereg §3). Words that back nothing the record claims (a short audit behind a
    readback claim) leave the mark "replayed-only" and the detail says why."""
    served = assemble(chunks) if chunks else {}
    if served and manifest is None:
        raise RecordError("audit chunks were served but no manifest was given to recompute them")
    marks: dict[int, str] = {}
    detail: dict[int, dict] = {}
    by_seq = {r["seq"]: r for r in log["loop_records"]}
    for seq in served:
        if seq not in by_seq:
            raise RecordError(f"audit words served for seq {seq}, which has no loop record")
    for seq, r in sorted(by_seq.items()):
        out = r["outcome"]
        if seq not in served:
            marks[seq] = "replayed-only"
            detail[seq] = {"served": False}
            continue
        if self_report_class(r) == "none":
            raise RecordError(f"seq {seq}: audit words served for a {out} candidate that staged nothing "
                              f"(no oracle self-report)")
        span, words = served[seq]["span"], served[seq]["words"]
        got = recompute(words, span, manifest)
        d = {"served": True, "span": span, "words": len(words), "recomputed": got, "compared": {}}
        ev = r["evidence"]
        commit = ev["sign_reply"]["commit"]
        if out == "STOP_LINK2":
            # the record's whole claim is staged != commit; the words must bear it out
            d["compared"]["staged_sha256 != commit"] = got["staged_sha256"] != commit
            if got["staged_sha256"] == commit:
                raise Falsified(f"seq {seq}: STOP_LINK2 claimed staged != commit, but the served "
                                f"staging recomputes to the signed commit {commit[:16]}…")
            marks[seq] = "audited"
            detail[seq] = d
            continue
        oracle = ev.get("app_oracle_record")
        if oracle is None:
            raise RecordError(f"seq {seq}: audit words served but the {out} record carries no app_oracle_record")
        for k in ("staged_stream_sha256", "staged_sha256"):
            d["compared"][k] = got[k] == oracle[k]
            if got[k] != oracle[k]:
                raise Falsified(f"seq {seq}: served raw words recompute {k} = {got[k][:16]}…, "
                                f"the record claimed {oracle[k][:16]}… (prereg §3: audited words do not "
                                f"recompute the compact record)")
        if span == "streams+readback":
            d["compared"]["readback_sha256"] = got["readback_sha256"] == oracle["readback_sha256"]
            if got["readback_sha256"] != oracle["readback_sha256"]:
                raise Falsified(f"seq {seq}: served readback frames recompute readback_sha256 = "
                                f"{got['readback_sha256'][:16]}…, the record claimed "
                                f"{oracle['readback_sha256'][:16]}… (prereg §3)")
            marks[seq] = "audited"
        else:
            # a streams-only audit behind a record that claims a readback backs link 2 but
            # nothing about link 3: not audited, and the detail says so
            marks[seq] = "replayed-only"
            d["short"] = "streams-only audit cannot back the readback_sha256 this record claims"
        detail[seq] = d
    return marks, detail
