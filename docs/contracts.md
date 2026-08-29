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
  readable: [0x2004, 0x2008, 0x2010, 0x2014, 0x2018, 0x201C, 0x2020, 0x2024, 0x2028]
  status_reserved_mask: 0xF8000000 # bits that read zero when the carrier answers
  heartbeat: {offset: 0x2028, width_bits: 32, advances_per_s_min: <n>, advances_per_s_max: <n>}
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
staged_sha256: <hex>               # link 2: md.l of the staged DDR stream's frames, BEFORE the DMA
write: {dma: [src, dst, src_len, dst_len], int_sts_after: <hex>, error_bits: [], ctrl_before: <hex>, ctrl_after: <hex>}
readback_sha256: <hex>             # link 3: pinned PCAP read of each candidate frame
readback_records: [stage_record...]
configuration_valid: true|false    # the §3 predicate, recomputed by the validator from the fields above
transport_rereads: [...]
```

### `arm_record` — 1.0.0

```yaml
schema: arm_record
schema_version: "1.0.0"
oracle_record_sha256: <hex>
gate_verdict_sha256: <hex>
epoch: 0                           # must equal both referenced records' epoch
axi_before: {status: <hex>, fault: <hex>}   # ¬recovery_required ∧ fault == 0 checked here
armed_at: <time>
```

### `score_record` — 1.0.0

```yaml
schema: score_record
schema_version: "1.0.0"
arm_record_sha256: <hex>
scores: [uint32 x 6]               # the PL's per-LUT match counters, read over the pinned AXI words
heartbeat: {before: <n>, after: <n>}
host_prediction: [uint32 x 6]      # from the host oracle over the candidate's INIT values
match: true|false
```

### `run_log` — 1.0.0

Ordered list of the records above for one session, plus the ruling's sha256, the summary's
raw UART log reference, and `epoch_final`. **Validator rule (the interlock's teeth):** a
`score_record` is valid only if its `arm_record`'s `oracle_record` has
`configuration_valid == true` recomputed from its own fields, and all three share one
epoch with the `gate_verdict`. A run log that violates this is not "flagged" — it is
rejected, and the line's kill criterion 1 (`p3_architecture.md` §7) applies.

## Import manifest

`docs/import_manifest.md` will be created at the first import (L0 exit), in
`zynq-psmap`'s form: every non-original file with its sha256, size and source commit, a
two-way closure test over `git ls-files`, and a "deliberately not imported" list. Until
then this repository contains only original documents.
