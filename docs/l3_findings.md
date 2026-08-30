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

## Diagnostic session (ruling `whole-of-probe P3-L3-diag` `2026-08-30-02`) — FABRIC_BLANK; root cause: host instrument (D-cache)

PCAP phase (`evidence/l3diag_17A6_2026-08-30-02/`): setup load → env0 write **WRITTEN** →
read `A20` **BLANK** — the mismatch reproduced at **phase 0, after a single envelope**, so
the multi-envelope hypothesis is dead. Per the stop semantics no further writes; closing
reads: `A20` BLANK, `C1A` PASS (base), `C20` PASS (base). Seal, then the terminal JTAG read
by the signer principal (first run refused by sudo because the runner passed a relative
evidence path — never reached the pod; fixed, retried under the same ruling):
`A20` = blank, `C1A` = base, `C20` = base, `STAT 0x46107ffc`, `CRC_ERROR = 0`.
Adjudication: **FABRIC_BLANK** — the write never landed in the fabric; PCAP readback told
the truth.

Root cause, established from the UART logs of the three runs (order of commands):

| run | first `dcache off` | first staged word (`mw.l 0x10400000`) | result |
|---|---|---|---|
| L2 run #3 | #44 (inside the first readback plan) | #953 | write landed, readback bit-exact |
| L3 session #1 | #1654 (first readback, after the writes) | #18 | BLANK |
| diagnostic | #563 (after the write) | #17 | BLANK |

The L3 write path staged the stream with the **D-cache on**: `mw.l` landed in L1/L2, the
devcfg DMA read stale DDR (a fresh boot: no SYNC word → the configuration logic ignored
the transfer, `D_P_DONE` set, no error bits), and the link-2 `md.l` re-read went through
the cache and "confirmed" a stream the DMA never saw. psmap's *read* plan carries a
verified `dcache off` step; its *write* plan does not, and every earlier write on this line
(P1, P2, L2) happened to follow a read. Two lessons, recorded: (1) link 2 is only evidence
of what the DMA sees if the cache is off — a verified `dcache off` is now a precondition of
staging (`l3_runner.ensure_dcache_off`, used by L2/L3/L4; the fake models the cache and
reproduces the defect); (2) "WRITTEN" from devcfg (`D_P_DONE`, no error) says nothing
about whether configuration happened — only link 3 does, which is why the runner never
armed. zynq-psmap's write plan has the same latent gap; it is noted here, not changed there.

Scope: session #1's STOP and this diagnostic are **host-instrument outcomes**; no board
or fabric fault is indicated (JTAG: CRC_ERROR 0, frames as expected for an unconfigured
write). The `unprovisioned` control has still not been exercised.

## Diagnostic run #2 (ruling `whole-of-probe P3-L3-diag` `2026-08-30-03`, with the fix) — NO_REPRODUCTION

Same sequence with `ensure_dcache_off` before every staging
(`evidence/l3diag_17A6_2026-08-30-03/`): phase 0 env0 WRITTEN → `A20` **PASS**
(`15cb05e6…`, 2 non-zero words); phase 1 env1 WRITTEN → `A20` PASS, `C1A` PASS; phase 2
env2 WRITTEN → `A20`, `C1A`, `C20` all PASS. Zero disruptions, zero re-reads. Terminal JTAG
(signer principal): `A20` = `15cb05e6…`, `C1A`/`C20` = base, `STAT 0x46107ffc`,
`CRC_ERROR = 0`. Adjudication **NO_REPRODUCTION** — every FAR CONSISTENT across PCAP
readback and JTAG.

What this establishes (scoped to 17A6, this carrier, U-Boot): with the D-cache off, a
three-envelope PCAP write lands frame-exact in the fabric, PCAP readback after each
envelope reports it faithfully, and later envelopes do not disturb earlier ones. The root
cause of session #1 and diagnostic #1 was the host instrument and is fixed and
board-verified. Session #1 (`unprovisioned`) can be re-run under a new `P3-L3` ruling.
