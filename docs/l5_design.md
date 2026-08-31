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
| staging buffers (3 × 534 words) | `0x1040_0000` | 6.4 KiB | non-cacheable — **= psmap's pinned `WR_BUF`, the same address in the same role** (l3_runner staged here; reusing the name avoids a second staging address) |
| identity page | `0x1044_0000` | 24 words | non-cacheable |
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

## 5a. The firmware (added in the same batch)

| file | standing |
|---|---|
| `firmware/p3_derive.[ch]` | the pure half — hashes, derive, stream build/parse, the pinned readback and cleanup command streams, base64url, the nonce model, the identity page. **Host-compiled and executed** against the Python reference over all 256 corpus entries (`tests/test_firmware_twin.py`) |
| `firmware/p3_data.h` | generated by `host/gen_firmware_data.py` from the phenotype manifest (15 pinned frames, 3 envelopes, the 292 addresses in canonical order); the suite fails if it is stale |
| `firmware/p3_app.c` | the board half — HAL + state machine mirroring `l5_refloop.py`. **Never compiled**; checked by `tests/test_firmware_audit.py` |
| `firmware/p3_search.c` | the reference sampler behind §4.1's interface; deterministic, seeded by the host |
| `firmware/Makefile` | `make twin` builds the host driver only; the cross recipe is recorded, deliberately not wired to a target |

The split is the point: everything that can be proven on the host was moved into
`p3_derive.c`, so what remains unexecuted is HAL and sequencing, and the sequencing has a
Python twin that *is* executed.

## 6. What remains before a board request (in order)

1. ~~The C application mirroring `l5_refloop.py`, the corpus check and the audit tests~~ —
   **done** (§5a; 256/256 bit-exact, 41 firmware tests).
2. ~~The L5 manifest~~ — **done**: `manifests/l5_manifest.json`, with the four
   build-time fields explicitly `null` under `pinned_at_build`.
3. ~~The L5 preregistration~~ — **done**: `docs/l5_prereg.md` (N = 8, every candidate
   audited, PASS/HOLD/KILL fixed in advance).
4. ~~The review package~~ — **done**: `docs/l5_review_package.md` (D5 step 2), which names
   the six decisions the owner is asked for, the toolchain among them.
5. **Owner's batch review** → one authorisation for build + rulings
   (`whole-of-probe P3-L5`, `provisioning P3-K`) + the board sequence. Not yet given.
6. The per-candidate time budget: still a measurement, not an assumption (spec §4.7).
