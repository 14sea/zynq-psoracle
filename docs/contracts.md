# Contracts — versioned artifacts across the three parties and the two source repositories

> **Status note (2026-08-31):** statements about rung status in this document are historical — what was true when it was written. The canonical status is `docs/status.md`.


Policy (inherited verbatim from `zynq-autoehw/docs/schema.md`): every artifact carries
`schema` and `schema_version`; **MAJOR** = incompatible field change, **MINOR** = additive
optional field; a consumer **rejects** a foreign MAJOR and **ignores** unknown MINOR fields;
each schema has a standalone validator and a conformance fixture shared by every consumer;
a reported result must replay from artifacts alone. Initial versions here are `1.0.0`
drafts; the freeze happens when the first validators and fixtures land (L0's exit).

Hashes are sha256 over big-endian 32-bit words unless a field says otherwise — the domain
`zynq-psmap` and `zynq-fabricmap` already share (`frame_sha256`, `candidate_sha256`).

## Imported schemas (consumed as-is, by version)

| schema | version | origin | consumed for |
|---|---|---|---|
| `zynq-psmap/pcap_probe_plan` | 1 | `pcap_probe_plan.build_plan` | the pinned PCAP read |
| `zynq-psmap/pcap_write_plan` | 1 | `pcap_write_plan.build_write_plan` | the pinned PCAP write (generalised in `candidate`, below) |
| `zynq-psmap/stage_record` | 1 | `pcap_probe_runner.execute_plan` | link-3 evidence |
| `zynq-psmap/write_record` | 1 | `p1_runner.execute_write_plan` | link-2 evidence and the DMA status |
| fabricmap `run_log` hash domains | as at `71666b02` | `run_log.py` | `candidate_sha256` / `readback_sha256` / `sequence_sha256` |

## New schemas

### `carrier_manifest` — 1.0.0

What the P3 carrier is, so that every other artifact can be checked against it.

```yaml
schema: carrier_manifest
schema_version: "1.0.0"
bitstream_sha256: <hex>            # the setup load; SHA-gated by the session
frame_table_sha256: <hex>          # digest over all frames (psmap diag_pcap_target_select)
part: xc7z010clg400-1
board_roles: {"17A6": verify}      # identity requirements the session enforces
axi:
  base: 0x43C00000
  # Two classes, never conflated (owner review 2026-08-29):
  #   stable_state — the EIGHT words zynq-psmap P2 pinned (STATUS, FAULT, SCORE0..5);
  #                  the P2 equality invariant applies to these and only these.
  #   heartbeat    — the ONE word P3 adds; the L2 envelope invariant applies to it alone.
  stable_state: [0x2004, 0x2008, 0x2010, 0x2014, 0x2018, 0x201C, 0x2020, 0x2024]   # 8
  heartbeat: {offset: 0x2028, width_bits: 32,                                      # +1
              advances_per_s_min: <n>, advances_per_s_max: <n>}   # BOTH bounds, pinned
                                                                  # from a measured
                                                                  # no-read baseline before
                                                                  # the L2 ruling
  status_reserved_mask: 0xF8000000 # bits that read zero when the carrier answers
  arm: {offset: 0x2000, bit: 6}    # the ONLY host→PL write; carries no data
target_columns: [CLBLL_L_X2, CLBLM_L_X6]
target_fars: [0x00400A20, ...]     # blank in the base by design
no_icap: true                      # the design contains no ICAPE2 instance (L1 KILL if false)
```

### `candidate` — 1.0.0

The thing the host gate judges and the oracle witnesses. Generalises psmap's single-frame
write to the whitelist's frames.

```yaml
schema: candidate
schema_version: "1.0.0"
carrier_manifest_sha256: <hex>
frames: [{far: 0x00400A20, words: [101 x uint32]}, ...]   # FAR-ordered canonical set
candidate_sha256: <hex>            # over `frames`, FAR-ordered (run_log domain)
stream_words: [uint32...]          # the exact PCAP stream (psmap write-stream shape,
                                   # one FAR-set per sync..DESYNC envelope, no CRC write)
sequence_sha256: <hex>             # over stream_words
```

### `gate_verdict` — 1.0.0 (link 1; pure)

```yaml
schema: gate_verdict
schema_version: "1.0.0"
candidate_sha256: <hex>
writable: true|false
findings: [{kind: whitelist|flush|ecc|far|stream, ...}]   # bucketed by kind, never by message text
gate_tool: {name: gate_candidate.py, version: ..., source_commit: 71666b02...}
manifest_sha256: <hex>
```

### `oracle_record` — 1.0.0 (links 2 and 3; the PS oracle)

```yaml
schema: oracle_record
schema_version: "1.0.0"
session: {boardid: "17A6", epoch: 0, plmark: <hex>, identity_sha256: <hex>}
candidate_sha256: <hex>
staged_sha256: <hex>               # link 2: the candidate FRAMES extracted from the md.l re-read of the staged DDR stream, BEFORE the DMA (candidate_sha256 domain)
staged_stream_sha256: <hex>        # link 2: the WHOLE staged stream as re-read (sequence_sha256 domain) — never substitutes for staged_sha256, nor vice versa
write: {dma: [src, dst, src_len, dst_len], int_sts_after: <hex>, error_bits: [], ctrl_before: <hex>, ctrl_after: <hex>}
readback_sha256: <hex>             # link 3: pinned PCAP read of each candidate frame
readback_records: [stage_record...]
configuration_valid_hw_expected: true|false   # the host's own prediction of the PL latch; evidence, not the gate
transport_rereads: [...]
```

### `lut_truth_table` — 1.0.0

Bit order of a target LUT's 64-bit truth table relative to `INIT[63:0]`, which input is
A1…A6, and the base values of the uncertified positions (they are part of the table the
fabric will exhibit). Derived by the gate signer from the candidate's INIT bits through the
certified map; identical function on the RTL side. Conformance fixture: fabricmap's
`known_answer.json` LUT0 (`actual_init`, `target_init`, mutable mask).

### `arm_mac` — 1.0.0

SipHash-2-4, 128-bit key, message = `candidate_commit` (32 bytes) ‖ `expected_tables`
(48 bytes) ‖ `nonce` (8 bytes); 128-bit tag. Fixtures: the published SipHash vectors plus
three repository vectors (a known candidate, its replay with a different nonce, a
one-bit-different table). Key: never in any artifact.

### `arm_record` — 1.0.0

```yaml
schema: arm_record
schema_version: "1.0.0"
oracle_record_sha256: <hex>
gate_verdict_sha256: <hex>
epoch: 0                           # must equal both referenced records' epoch
nonce: <hex64>                     # read from the PL in this session; consumed once
candidate_commit: <hex256>         # the FULL candidate_sha256 (no truncation)
expected_tables: [6 x hex64]       # lut_truth_table 1.0.0
tag: <hex128>                      # arm_mac 1.0.0, produced by the gate signer ONLY
signer: {principal: gate-signer, key_id: <hex>}   # key_id = sha256(K) of the key provisioned this session
key_loaded_observed: true          # STATUS bit 11 as read before the ARM; a score needs it true (rule v)
axi_before: {status: <hex>, fault: <hex>}   # ¬recovery_required ∧ fault == 0 checked here
armed_at: <time>
```

### `score_record` — 1.0.0

```yaml
schema: score_record
schema_version: "1.0.0"
arm_record_sha256: <hex>
configuration_valid_hw: true       # read from the PL; a score_record with false is invalid
hw_candidate_commit: <hex256>      # the commit the PL exposes as the one it armed for
functional_readout: [6 x hex64]    # the PL's sweep result, read-only
scores: [uint32 x 6]               # the PL's per-LUT match counters, read over the pinned AXI words
heartbeat: {before: <n>, after: <n>}
host_prediction: [uint32 x 6]      # from the host oracle over the candidate's INIT values
match: true|false
```

### `negative_control` — 1.0.0 (L3's on-board negative controls)

```yaml
schema: negative_control
schema_version: "1.0.0"
kind: unsigned | replay | other_candidate | wrong_table | unprovisioned | wrong_key
arm_record_sha256: <hex>           # the positive arm_record of the same session (the fabric holds its candidate)
nonce: <hex64>                     # the PL nonce this control consumed
configuration_valid_hw: false      # anything else is a KILL, not a record
fault: 12|13|15                    # F_ARM_NOKEY for unprovisioned; F_ARM_AUTH for unsigned/replay/other_candidate/wrong_key; F_ARM_TABLE for wrong_table
scored: false
refused_as_expected: true|false    # fault == the kind's expected fault
```

A fault is sticky until reset (L1), so one session carries the positive case and **one**
negative control; the three the ladder names take three rulings. Rule (vi) in the run-log
validator: every `negative_control` must reference an `arm_record` in the log and be
`refused_as_expected`.

### `run_log` — 1.0.0

Ordered list of the records above for one session, plus the ruling's sha256, the summary's
raw UART log reference, and `epoch_final`. **Validator rules — evidence consistency, which
never replaces the PL MAC gate:** a `score_record` is valid only if (i) its `arm_record`,
`oracle_record` and `gate_verdict` share one epoch, (ii) `hw_candidate_commit ==
candidate_commit == gate_verdict.candidate_sha256`, (iii) `functional_readout ==
expected_tables`, (iv) the oracle's two hashes (staged stream, candidate frames — recorded
separately) both match, (v) `configuration_valid_hw` is true. A run log that violates any
of these is rejected, and the line's kill criterion 1 applies.

### key register and provisioning (D4 option A)

`0x2160‥216C` four key words (word 0 = `K[127:96]` of the key as a 128-bit little-endian
integer), write-only, accepted only while `key_loaded == 0`; CTRL bit 8 `key_commit` sets
`key_loaded` (STATUS bit 11); afterwards a key write is SLVERR and `key_commit` is ignored;
reads are SLVERR; only reconfiguration clears `key_loaded`. Written **only** over the DAP
mem-AP by the signer principal (`host/provision_key_jtag.py`); these offsets are in neither
the runner's readable nor writable AXI map. `arm_record.key_loaded_observed` (required) is
the runner's reading of bit 11 before the ARM; rule (v) rejects a score whose arm record
has it false. Negative kinds `unprovisioned` (expected fault 12) and `wrong_key` (13) are
**pre-positive** controls: the positive attempt itself is the refused ARM.

### `carrier_manifest` additions (1.0.0)

`axi.nonce` (read-once word), `axi.arm_payload` (24 write-only staging words + the ARM
strobe), `axi.hw_candidate_commit` and `axi.functional_readout` (read-only), `mac:
{algorithm: siphash-2-4-128, key_id: <sha256 of K, never K itself>}`, and the statement
that no readable register or readback frame carries `K`.

## Standalone-plane schemas (D1 — `docs/d1_standalone_spec.md` §7; 1.0.0 drafts)

Added under the D5 batch after D1's review #2 (ACCEPTED WITH Q7 CONDITION). They apply
**only** when `control_plane == standalone`; no L2–L4 rule is touched. The type split is
deliberate: a validator that requires a host-observed `oracle_record` never accepts an
`app_oracle_record` (the application's self-report) in its place.

### `d1_genome` (a value contract, not a record)

292 bits over the manifest's whitelisted `(far, word, bit)` addresses in **ascending
order**, absolute values, packed little-endian into ten 32-bit words (bits 292..319 zero);
canonical text form = the ten words as 8 hex chars each, word 0 first (80 chars). The
derive function (base target frames + genome bits + word-50 ECC recompute, flush frames
verbatim) is `host/p3_genome.py`; its conformance corpus is
**`fixtures/d1_corpus_v1.json` — `N = 256` pinned (review #2 Q7)**: entry 0 = the blank
candidate, entry 1 = the known answer, entries 2..255 from per-index seeds
`d1-corpus-v1/<i>`; each entry pins `candidate_sha256`, `sequence_sha256` and the six
expected tables. A C twin must reproduce every entry.

### `app_identity` — 1.0.0

Spec §3b: `control_plane: standalone`, `pss_idcode`, `token` (full 128-bit hex), `uboot_epoch`,
`carrier_sha256` (full 256-bit), `nonce_at_start`, `status_at_start`, `fclk0_hz_decoded`,
`app_epoch`, `findings` (non-empty ⇒ the loop must not have started).

### `sign_request` / `sign_reply` / `sign_refusal` — 1.0.0

§4.3/§5b: request = `token`, `app_epoch`, `seq` (strictly increasing from 1), `genome`
(80 hex), `nonce` (the application's PL reading). Reply = `seq`, `commit` (full
candidate_sha256), `expected_tables` (6 × hex64), `tag` (hex128). Refusal = `seq`,
`finding_kinds` (fabricmap kinds; **a refusal is a per-candidate outcome, never an
epoch end**).

### `notary_log` — 1.0.0

Host-side, written by the signer/relay: `token`, `entries` (ordered `{seq, request,
reply | refusal, at}` — `seq` strictly increasing, exactly one answer per request).
Rule (vii) cross-checks it against the application's records.

### `app_oracle_record` — 1.0.0

The application's links 2 and 3 for one candidate: `seq`, `staged_sha256`,
`staged_stream_sha256` (distinct domains, as `oracle_record`), `readback_sha256`,
`write` (per-envelope DMA/INT_STS evidence), `audit_available`; when audited, the audit
result is attached by the collector. **Never a substitute for `oracle_record`.**

### `loop_record` — 1.0.0

One per candidate: `seq`, `genome`, `outcome ∈ {SCORED, REFUSED_BY_GATE, STOP_LINK2,
STOP_LINK3, REFUSED_BY_PL, STOP_AXI}`, `verified ∈ {audited, replayed-only}` (rule ix),
and `evidence` — the per-outcome required set: `SCORED` ⇒ `sign_reply`,
`app_oracle_record`, ARM fields (`nonce_before/after`, `status_after`, `fault_after`,
`key_loaded_observed`, `hw_candidate_commit`, `functional_readout`, `scores`, heartbeat
pair); `REFUSED_BY_GATE` ⇒ `sign_refusal` only; the STOP outcomes ⇒ what was observed up
to the stop. Validator checks the §7 consistency rules per record (commit chain, readout
== tables, readback == commit for SCORED).

### `session_summary` — 1.0.0

`token`, `epoch_end: {kind ∈ COMPLETED|STOPPED|PROTOCOL|CRASHED, reason, last_seq}`,
`counts`, `closing: {restore, baseline, unsigned_control}` each `done | not_reached`,
`audit: {audited, total}`, `crc_dropped`, `drop_budget`, `written_by: app | collector`.
Rule (viii)'s closing obligations are checked against `epoch_end.kind` (spec §3c/§4.0);
`CRASHED` must be `written_by: collector`.

### L6 additions (additive; proposed 2026-09-01 with the §4 instrument batch, for the §2 image)

`loop_record` 1.1.0: `arm ∈ {random_safe, map_guided}` on every candidate record, **absent**
on the two baseline brackets (seq 1, seq N+2). Checked by
`validators/records.check_arm_schedule` against the preregistered schedule
(`host/l6_schedule.py`), optionally against the operators' host twin
(`host/l6_operators.py`).

`app_identity` 1.1.0: `master_seed` (int, the identity page's seed word), `schedule_mode ∈
{abba, random_safe_forced, map_guided_forced}` (the page's flags bits 2–3),
`operator_data_sha256` (64 hex — the hash of the map data compiled into the image, which
the host regenerates from the pinned `local_map.json`). Checked by `check_l6_identity`.

Standalone `run_log` (host-written keys): `timing` — `clocks`, `t_go_mono`,
`records[seq] = {t_signreq, t_reply, t_auditreq, hb[], audit[], t_rec, hb_count,
audit_chunks, wall, breakdown}` on the host's monotonic clock; `l6` — the session plan
(mode, master seed, N, schedule, audit seqs, expected frames, CRC budget, timeout and
their inputs). The validator ignores both; `host/l6_rate.py` refuses a log without
`timing`. Evidence companions: `console.ts.log` (`<mono> <wall> <line>` per console line;
`console.log` stays the verbatim bytes), `timeline.json`, `rate_report.json`.

### `run_log` additions (additive → 1.1.0 for standalone logs)

`control_plane: uboot | standalone` (absent = `uboot`), `identity_page`, `app_identity`,
`notary_log_sha256`, `loop_records`, `session_summary`. Rules (vii)–(ix) — spec §7 — are
enforced by `validators/records.validate_standalone_run_log`; rules (i)–(vi) semantics
apply per `loop_record` with `app_oracle_record` in `oracle_record`'s role **only** on the
standalone plane.

## Import manifest

`docs/import_manifest.md` will be created at the first import (L0 exit), in
`zynq-psmap`'s form: every non-original file with its sha256, size and source commit, a
two-way closure test over `git ls-files`, and a "deliberately not imported" list. Until
then this repository contains only original documents.
