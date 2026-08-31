# L5 design record — the standalone loop (host-only; draft under the D5 batch)

> **Status note:** design record only. Written under D5's host-only batch after D1's review
> #2 (ACCEPTED WITH Q7 CONDITION). It authorises nothing: **no L5 build, no board contact,
> no ruling.** The canonical status is `docs/status.md`; the governing specification is
> `docs/d1_standalone_spec.md` (v0.2).

## 1. Pinned quantities (the future L5 manifest carries all of these)

| name | value | why this value |
|---|---|---|
| **`N` — conformance corpus size** | **256** (`fixtures/d1_corpus_v1.json`) | review #2's Q7 condition: pinned, not an unbound quantifier. Entry 0 = blank candidate, entry 1 = known answer, 2..255 from per-index seeds `d1-corpus-v1/<i>`. A C twin must reproduce every entry's `candidate_sha256`, `sequence_sha256` and six tables |
| `W` — raw-word evidence ring depth | 512 candidates | ≈ 16 KiB/candidate (3×534 staged + 12×202 readback + 24 ARM words) → 8 MiB, inside the DDR region psmap's committed runs already use; audit-on-request reaches back `W` candidates (spec §4.7) |
| `H` — heartbeat interval | 10 s | matches L2's sub-sample cadence (≤ 20 s guard); collector declares `CRASHED` after `3 × H` of silence (spec §3c) |
| CRC drop budget | 16 lines / session | psmap's observed console fault rate is single lost/garbled lines per multi-minute session (L3 #4/#5 each logged 1 re-read); 16 is an order of magnitude of headroom — exceeding it means the link itself is sick (`PROTOCOL`, kill criterion 3 territory) |
| audit rate | **prereg item, not pinned here** | the L5 preregistration pins it; working recommendation 1/16 (the collector requests an audit for ~6% of candidates; rule (ix) reports the achieved set) |
| watchdog period | `3 × H` = 30 s | spec §6a: kicked only from the main loop after each framed line |

## 2. DDR layout (all sentinel-verified at session start; addresses are a choice, the verification is the guarantee — psmap §6 doctrine)

| region | address | size | cacheability (app's own MMU table) |
|---|---|---|---|
| application image + stack/heap | `0x0200_0000` | ≤ 4 MiB | normal, cacheable |
| readback command buffer | `0x1020_0000` | 43 words | **non-cacheable** (psmap's pinned address, same use) |
| readback destination buffer | `0x1030_0000` | 202 words | non-cacheable |
| identity page | `0x1040_0000` | 24 words | non-cacheable |
| staging buffers (3 × 534 words) | `0x1044_0000` | 6.4 KiB | non-cacheable |
| evidence ring (`W` = 512) | `0x1080_0000` | 8 MiB | non-cacheable |

Non-cacheable via `Xil_SetTlbAttributes` on the app's own translation table, attributes
read back and recorded in `app_identity` (spec §4.2 — the L3-diagnostic bug class closed by
construction, not by per-op cache calls). No buffer crosses a 4 KiB boundary at its
transfer sizes; all are 64-byte aligned. The carrier setup load's `0x0400_0000` and
psmap's `0x1000_0000`/`0x1010_0000` are untouched.

## 3. Image and boot

Standalone BSP application, **no `ps7_init`** (U-Boot's DDR/clock state is inherited and
must not be re-created — spec §1: the PL, `key_loaded` and the nonce survive `go`).
Load: the same sha-gated ymodem path as the setup load, to `0x0200_0000`; entry = load
address; `go` ends the U-Boot epoch. Drivers: `XDcfg` (devcfg_v3_9) for the pinned DMA
tuples only; the private timer for the watchdog; the global timer (`0xF8F00200`) for
timestamps, frequency derived by decoding the PLLs (never a remembered constant). The
firmware-source audit tests (host-side, over the C source) must show: no key-register
offsets (`0x2160‥216C`), no clock/reset/level-shifter writes, only the legal DMA tuples,
AXI accesses confined to the runner map.

## 4. Toolchain — the one open decision for the build authorisation

No ARM bare-metal compiler exists on this host (`arm-none-eabi-gcc` absent; Vitis not
installed; `/home/test/Xilinx/2025.2/data/embeddedsw` provides the BSP/driver *sources*
only).

| option | pro | con |
|---|---|---|
| **xPack `arm-none-eabi-gcc` (pinned release tarball)** — recommended | exact version pinned in the manifest; no system-wide install; reproducible | download needed (force IPv4 on this box — WSL IPv6 is broken) |
| Debian `gcc-arm-none-eabi` via apt | one command (sudo, owner-run per the sudo-handoff practice) | version drifts with the distro; weaker pin |
| Vitis install | vendor-blessed BSP build flow | tens of GB for one compiler; nothing else of it is used |

The choice is the owner's at the build authorisation; the manifest records
`toolchain: {name, version, sha256}` either way.

## 5. Host-side pieces (this batch — done)

- `host/p3_genome.py` — the derive function + the pinned corpus generator; tests pin the
  known-answer and blank round-trips bit-for-bit and that every derived candidate passes
  the real gate.
- `host/sign_arm.py sign_genome` — the signer's own derive + gate + tables + tag; a gate
  refusal is data (exit 0), never a channel error.
- `host/l5_notary.py` — §5b framing (full 128-bit token, CRC, drop budget), the relay
  (notary_log for rule vii), the collector (§3c epoch classification, CRASHED summary).
- `host/l5_refloop.py` — the application's reference state machine (identity gate →
  brackets → per-candidate transaction → taxonomy); the C application mirrors it.
- `validators/records.py` — the standalone schemas and `validate_standalone_run_log`
  (rules vii–ix).
- `fixtures/d1_corpus_v1.json` — `N = 256`, regenerable, spot-checked by the suite.

The end-to-end rehearsal (`tests/test_l5_refloop.py`) runs the reference loop against a
fake standalone PL through the real relay and the **real signer**, and the resulting log
passes `validate_standalone_run_log` — including the opening baseline scoring fabricmap's
`base_restore` `[18,22,20,20,20,18]` through the oracle model. The fake proves sequencing
and refusals; it proves nothing about the PL RTL or the transport (L3's fake had the same
standing).

## 6. What remains before a board request (in order)

1. The C application (firmware) mirroring `l5_refloop.py`, with the corpus check
   (`N = 256`, every entry) and the firmware-source audit tests green host-side.
2. The per-candidate time budget measured on the fake→estimated, then on the board
   (expectation: the notary round-trip dominates; spec §4.7).
3. The L5 manifest (this file's §1/§2 values + image sha + toolchain).
4. The L5 preregistration (audit rate, session duration, budget, seed — deterministic/
   test-mode label per review #2 Q6).
5. The whole review package (D5 step 2) → owner batch review → one authorisation for
   build + rulings (`whole-of-probe P3-L5`, `provisioning P3-K`) + the board sequence.
