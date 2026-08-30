# L3 on 17A6 — findings

## Session #1 (ruling `whole-of-probe P3-L3` `2026-08-30-01`, `--negative unprovisioned`) — STOP LINK3_MISMATCH

First P3 board contact for L3. Boundary verified as the runner beforehand (R1–R5 PASS,
`evidence/boundary/principal_boundary_2026-08-30-l3-01.json`). No provisioning (as ruled).

What happened (`evidence/l3_17A6_2026-08-30-01/`): link 1 passed (known answer); setup load
of `builds/p3/p3.bit`; **three envelopes staged, re-read (link 2 equal) and written —
`L3_write_0/1/2` all WRITTEN** (D_P_DONE, no error bits); link 3's first readback,
`0x00400A20`, came back **BLANK**: all 202 words zero, sentinel fully overwritten (so the
DMA delivered data), frame half = the blank frame (`0441772f…`). The runner stopped —
**no ARM, no provisioning, no score**; run log holds only `candidate` + `gate_verdict`.
Zero disruptions, zero re-reads. Ruling consumed with the STOP.

The contradiction: **L2 run #3 wrote the same envelope 0 and read `0x00400A20` back
bit-exact** (`15cb05e6…`, 2 non-zero words). Same board, same bitstream, same write and
readback plans. The one difference is that this session wrote **three FAR sets
(envelopes 0, 1, 2) back-to-back before reading**; every earlier PCAP write on this line
(psmap P1, L2) wrote one envelope and read immediately.

What this session does not tell: whether `0x00400A20` is really blank in the fabric now
(the later envelope writes cleared it, or the auto-increment/pending-frame behaviour after
a second FAR set landed frames elsewhere) or whether the PCAP **readback** path returns
zeros after multi-envelope writes (fabricmap's ICAP carrier saw exactly "writes landed,
internal readback blank" — the readback interlock). The session stopped at the first
frame; the other eleven were not read (instrument fix below).

Instrument changes after this session (host-only, `4b2f4cf`→): link 3 now reads **all
twelve** frames before stopping and names every mismatch (reads are non-destructive);
per-envelope write records are persisted as files.

Proposed diagnostic session (needs its own ruling; nothing done): after the setup load,
write envelope 0 → read `A20`; write envelope 1 → read `A20` and `C1A`; write envelope 2 →
read `A20`, `C1A`, `C20`; then, sealed, a **terminal JTAG read** of `A20`/`C1A`/`C20`
(psmap's `probe_jtag_config_read`, the P1 method) to settle "fabric blank" vs "PCAP
readback blank". Either outcome is a real finding for the write path this line depends on.

Scope: this STOP is a **negative observation about the multi-envelope write/readback
path**, not about the ARM gate (never reached) and not about `unprovisioned` (not exercised).
