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

## Session #1 re-run (ruling `whole-of-probe P3-L3` `2026-08-30-03`, `--negative unprovisioned`) — PASS

`evidence/l3_17A6_2026-08-30-03/`, 12 min 21 s, zero disruptions, zero re-reads. Boundary
R1–R5 PASS beforehand. No provisioning (as ruled); `key_loaded_observed = false`.

- link 1: known answer writable; `candidate_sha256 4f14db96…`.
- stage / link 2 / write: three envelopes, each `dcache off` (verified) → staged → re-read
  equal → **WRITTEN**.
- link 3: **all twelve target frames read back as the candidate** — `readback_sha256` =
  `staged_sha256` = `candidate_sha256` = `4f14db96…` (rule (iv) holds).
- ARM: STATUS before `0x100` (alive, idle, no key), FAULT 0; after the strobe STATUS
  `0x182` (fault, recovery_required, alive), FAULT **12 = F_ARM_NOKEY**;
  `configuration_valid_hw` 0, no score; **nonce consumed**: `9e3779b97f4a7c15` →
  `dc1b77ae0bf34dad`, which equals the host xorshift model's successor (`validators/nonce.py`)
  — the PL's nonce generator matches the model on silicon.
- negative_control `unprovisioned`: `refused_as_expected = true`; run log validates
  (rules (i)–(vi); no score_record, as required).

Scope (as ruled): only the `unprovisioned` control on this carrier/board; nothing about
the positive case or the other controls. What it also shows, as observation: the full
gate → stage → link 2 → write → link 3 chain over all twelve frames on 17A6.

## Session #2 attempt 1 (rulings `P3-L3 2026-08-31-01` + `P3-K 2026-08-31-01`) — STOP before staging: host instrument (ruling consumption model)

The operator pre-claimed the `provisioning P3-K` ruling in `rulings/` before launching;
the signer's ruling check treats a `.consumed` companion as "already used" and refused to
provision → the runner stopped after the setup load, **before any staging, write, ARM or
pod contact**. Both rulings are consumed (`evidence/l3_17A6_2026-08-31-01/`, 3 min 23 s,
zero disruptions). No board finding.

Fix: a `provisioning P3-K` ruling is consumed **by the signer itself** at execution time
(an O_EXCL marker in `/var/lib/p3signer/consumed/`, keyed by the ruling file's sha256; a
second execution with the same ruling is refused as "already used"); the runner records the
session outcome beside the ruling only **after** the run (`_record_pk`), never before. The
runbook is corrected accordingly. Tests exercise the marker with a dummy-adapter cfg
(`P3_PROVISION_CFG`) so no test can ever open the pod.

## Session #2 (rulings `P3-L3 2026-08-31-02` + `provisioning P3-K 2026-08-31-02`, `--negative unsigned`) — PASS

`evidence/l3_17A6_2026-08-31-02/`, 13 min 10 s, zero disruptions, zero re-reads. Boundary
R1–R5 PASS beforehand. First on-board key provisioning.

- **Provisioning (signer principal, DAP mem-AP)**: openocd 0.12 found both TAPs
  (`0x13722093`, `0x4ba00477`), wrote the four key words + `key_commit`, rc 0, no core
  halted; the runner then read STATUS `0x900` = alive + **key_loaded** (bit 11).
- links 1–3: known answer writable; three envelopes staged (`dcache off`), re-read equal,
  WRITTEN; **12/12 frames read back as the candidate**.
- **Positive ARM**: signer `key_id b4c022a2…`, nonce `9e3779b97f4a7c15`; after the strobe
  STATUS `0xf54` = cfg_valid_hw ∧ scorer_done ∧ tag_ok ∧ alive ∧ sweep_done ∧
  tables_match ∧ key_loaded, FAULT 0; **`HW_COMMIT` = the gate's `candidate_sha256`**;
  **`FUNCTIONAL_READOUT` = the signed expected tables**; **scores `[35, 22, 20, 20, 20, 18]`
  = the host prediction = fabricmap's published silicon scores for this candidate**;
  heartbeat advanced; nonce → `dc1b77ae0bf34dad` (= model).
- **`unsigned` control** (zero tag, same commit/tables, fresh nonce): FAULT **13 =
  F_ARM_AUTH**, cfg_valid 0, no score, nonce consumed → `64f0eeb9026e6076` (= model's
  second step).
- run log validates (rules (i)–(vi)); both rulings consumed (the P3-K one by the signer's
  own marker, the outcome recorded beside it by the runner afterwards).

What this establishes (17A6, this carrier, U-Boot): the PL-enforced interlock works
end-to-end on silicon — a gate-approved candidate, written over PCAP and witnessed by the
oracle, is scored **only** after the PL verified a tag produced by the signer principal for
this commit/tables/nonce and found the fabric's six truth tables equal to the signed
expectation; the PL exposes the same commit the gate hashed; an unsigned ARM on the same
fabric is refused and consumes the nonce. Still open for L3: `replay`, `other_candidate`,
`wrong_key` (and optional `wrong_table`), one session each.

## Session #3 (rulings `P3-L3 2026-08-31-03` + `P3-K 2026-08-31-03`, `--negative replay`) — PASS

`evidence/l3_17A6_2026-08-31-03/`, 13 min 8 s, zero disruptions, zero re-reads. Provisioning
rc 0, `key_loaded` observed. 12/12 frames read back as the candidate. **Positive ARM**: STATUS
`0xf54`, `HW_COMMIT` = gate hash, readout = signed tables, scores `[35, 22, 20, 20, 20, 18]`
= prediction (second reproduction of session #2's positive case on a fresh power-cycle).
**`replay` control** — the positive session's exact 24 payload words staged again after
the PL's nonce had stepped: FAULT **13 = F_ARM_AUTH**, cfg_valid 0, no score, nonce consumed
(`dc1b77ae…` → `64f0eeb9…`, = model). The tag that was valid one ARM earlier is worthless
now: the nonce binds a signature to one attempt. Run log validates; both rulings consumed.
