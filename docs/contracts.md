# Contracts — versioned artifacts across the three parties and the two source repositories

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
signer: {principal: gate-signer, carrier_manifest_sha256: <hex>}   # which key it signed for
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

### `run_log` — 1.0.0

Ordered list of the records above for one session, plus the ruling's sha256, the summary's
raw UART log reference, and `epoch_final`. **Validator rules — evidence consistency, which
never replaces the PL MAC gate:** a `score_record` is valid only if (i) its `arm_record`,
`oracle_record` and `gate_verdict` share one epoch, (ii) `hw_candidate_commit ==
candidate_commit == gate_verdict.candidate_sha256`, (iii) `functional_readout ==
expected_tables`, (iv) the oracle's two hashes (staged stream, candidate frames — recorded
separately) both match, (v) `configuration_valid_hw` is true. A run log that violates any
of these is rejected, and the line's kill criterion 1 applies.

### `carrier_manifest` additions (1.0.0)

`axi.nonce` (read-once word), `axi.arm_payload` (24 write-only staging words + the ARM
strobe), `axi.hw_candidate_commit` and `axi.functional_readout` (read-only), `mac:
{algorithm: siphash-2-4-128, key_id: <sha256 of K, never K itself>}`, and the statement
that no readable register or readback frame carries `K`.

## Import manifest

`docs/import_manifest.md` will be created at the first import (L0 exit), in
`zynq-psmap`'s form: every non-original file with its sha256, size and source commit, a
two-way closure test over `git ls-files`, and a "deliberately not imported" list. Until
then this repository contains only original documents.
