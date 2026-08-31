# L5 build findings — the firmware compiles; one decision remains

> **Standing.** This is the **post-build package** the D5 batch review asked for
> (`docs/l5_review_package.md` §5). It reports what the authorised build produced. It is
> host-only: an ELF was produced, **no board was touched, no ruling was created, nothing was
> pushed.** The canonical status table is `docs/status.md`.

## 1. What the build authorisation covered, and what it produced

The owner's D5 verdict authorised, continuously and host-only: *install/pin the toolchain,
compile the firmware, complete the manifest and the linker-map validation* — with **board,
ruling and any long run still paused**. All of that is done except the one item in §4.

| step | result |
|---|---|
| Toolchain (D-a) | **xPack `arm-none-eabi-gcc` 14.2.1-1.1** downloaded over IPv4, sha256 **verified against the publisher's `.sha`**, extracted to `toolchain/` (git-ignored). Pinned in `manifests/l5_manifest.json`. |
| BSP | hand-assembled Cortex-A9 **standalone** BSP (non-SDT) from Xilinx 2025.2 `embeddedsw` sources — startup/MMU/cache + `scuwdt` + a UART1 console glue — under `firmware/bsp/` (`build.sh`, `lscript.ld`, `include/`, `src/console.c`). |
| Compile | `p3_app.c` + `p3_derive.c` + `p3_search.c` compile **`-Wall -Wextra` clean** and link with **no undefined symbols** into `firmware/bsp/out/p3_app.elf`. **`p3_app.c` needed no source change to compile.** |
| `p3_derive.c` | cross-compiles for cortex-a9 **unchanged** → review-package §5.2 (a `p3_derive.c` change re-runs the corpus first) is trivially satisfied: there was no change. |
| Linker-map | validated (§3). |

## 2. Why there is no ARM compiler here even though Vitis is installed

`/home/test/Xilinx/2025.2/Vitis` exists (3.7 GB), but it bundles **no** `arm-none-eabi-gcc`
/ cortex-a9 compiler (2024.1+ Unified Vitis ships the bare-metal ARM GNU toolchain as a
separate download). So D-a's premise — "no ARM bare-metal compiler on this host" — **holds**;
the only inaccuracy in the design note was "Vitis not installed", and it changes nothing
because the installed Vitis does not provide the compiler. xPack remains the right choice.

## 3. The image and the linker-map validation

- **Load model:** raw binary at `0x0200_0000`, `go 0x0200_0000`. The reset vector at
  `0x0200_0000` is `b _boot` (`_boot` = `0x0200_00cc`), so a raw `go` enters correctly.
- **Footprint:** `0x0200_0000` → `_end` `0x0212_4ec0` = **≈ 1.19 MiB** (text 72 KiB, data
  2 KiB, bss ≈ 40 KiB, heap 1 MiB, stacks ≈ 20 KiB). Inside the ≤ 4 MiB budget
  (`docs/l5_design.md` §2). No section reaches the instrument buffers at `0x1020_0000`+ or
  U-Boot's `0x0400_0000`.
- **Provisional image sha256** (this build): `.bin` = `7540239fbba07e6a8a19d9081f8e21220f0fdac2f3ba7b48e88f34767da8005e`
  (81 940 bytes). Deterministic across comment-only edits (the `.elf` sha moves only because
  DWARF line tables shift; the shipped image is the `.bin`). **Not yet pinned in the manifest
  — see §4:** the watchdog decision may change `p3_app.c` and therefore this hash.

## 4. The watchdog (D-c) — the finding, and the owner's ruling

> **RULED 2026-08-31: option 2 — the watchdog is OFF for the first L5 session.** The owner's
> reasons: it changes no already-compiled, already-audited `p3_app.c`; the collector's
> 3 × H = 30 s silence → `CRASHED` already bounds a hang; session 1 is an N = 8 bounded
> bring-up where new, un-boarded prescaler behaviour is the wrong thing to add; and
> watchdog-on can be its own change and validation later without touching the interlock
> claim. Consequences, all recorded: the identity page is written with `flags.bit1 = 0`
> (`manifests/l5_manifest.json` `pinned_at_build.identity_page_flags`); `watchdog_load_value`
> is **not used** rather than unset; host recovery for a watchdog-off session is fixed in
> `docs/l5_prereg.md` §4; and because no firmware changed, **`app_image_sha256` is now final**
> — the image was rebuilt after the ruling and is byte-identical.
>
> **Latent hazard, guarded.** `P3_WDT_LOAD` is `0` in this image. Enabling the watchdog by
> flipping `flags.bit1` alone would load 0 — an immediate reset. The firmware gates both the
> arm and the kick on that bit, and `tests/test_firmware_audit.py` now *checks* that gating
> rather than merely documenting it. Turning the watchdog on is option 1 below: a firmware
> change, a new build, a new preregistration and a new ruling.

The finding that prompted the ruling:

D-c pins the watchdog at **3 × heartbeat = 30 s**, "computed from the private-timer clock at
build". Computing it exposes a gap the accepted decision did not account for:

- The A9 private watchdog counts a **32-bit** value down at **PERIPHCLK / (prescaler + 1)**.
- PERIPHCLK = CPU_6x4x / 2 = **333.33 MHz** (see §5 for the provenance and its one caveat).
- With the **prescaler = 0** (the reset default, and all `p3_app.c` sets), the longest
  representable interval is `(2^32 − 1) / 333.33 MHz` = **12.88 s**. **30 s cannot be
  loaded.**
- `p3_app.c` calls only `XScuWdt_LoadWdt` + `XScuWdt_Start`; it never programs the prescaler,
  and the driver has no `SetPrescaler` — the prescaler is a control-register field
  (`XSCUWDT_CONTROL_PRESCALER`, bits 15:8), so reaching 30 s **requires a new
  control-register write in `p3_app.c`**.

This is a firmware change, so per the stop-on-a-finding discipline it is **not applied
silently**. Options for the owner:

1. **Add a prescaler.** e.g. prescaler = 7 (÷8) → rate 41.67 MHz, `P3_WDT_LOAD = 1_250_000_035`
   → 30.00 s (or prescaler = 2 (÷3) → `3_333_333_429`). Minimal, faithful to D-c; adds one
   `XScuWdt_SetControlReg` before `Start`. The source audit already permits SCU-WDT writes
   (the app programs the watchdog); this stays inside that.
2. **Keep the watchdog off for session 1.** The prereg's N = 8 bounded session with the
   collector's `3 × H` silence → `CRASHED` already bounds a hang host-side; the identity page
   flag (`flags & 2`) gates whether the app arms the WDT at all. Then no `p3_app.c` change and
   the §3 image hash stands as final.
3. **Revisit H** so `3 × H ≤ 12.88 s` at prescaler 0 (e.g. H = 4 s → 12 s), which also
   touches `docs/l5_design.md`/manifest.

**Option 2 was taken.** `watchdog_load_value` is recorded as *not used* (not merely unset) and
`app_image_sha256` is pinned, since option 2 changed no firmware. Options 1 and 3 remain the
only routes to a watchdog-on session, each needing its own build, prereg and ruling.

## 5. Build constants and their provenance (the "confirm, don't guess" items)

The carrier deliberately carries **no PS7 clock/UART preset** — it inherits U-Boot's state
(`docs/l5_design.md` §3) — so the confirming source for the board constants is the **17A6
board evidence in this repo**, not an `.xsa`. Recorded in `firmware/bsp/include/xparameters.h`:

| constant | value | source | confirmed? |
|---|---|---|---|
| console UART | **UART1 @ 0xE000_1000** | D1 spec T1 ("the console (UART1)"); every board run relays through it | **yes** |
| ARM PLL | **1333.33 MHz** | `ARM_PLL_CTRL = 0x00028008` on 17A6 (`evidence/l2_17A6_2026-08-30-03/L2_0_fclk.json`), FDIV 40 × 33.333 MHz | **yes** |
| CPU_6x4x / PERIPHCLK | 666.67 / 333.33 MHz | **assumes 6:2:1**; `CPU_CLK_CTRL` (0xF8000120) was **not** captured in the board evidence | **assumed** — the one un-confirmed constant; affects only the watchdog computation |
| DDR size | ≥ 512 MiB (`HIGHADDR 0x1FFF_FFFF`) | the inherited map reaches `0x1080_0000`+8 MiB (`l5_design` §2) | inferred |

**The owner has ruled this a blocking pre-board preflight** (2026-08-31): `md.l 0xF8000120 1`
is read once at first power-on and stored with the session evidence, and **until that read
exists no timing conversion derived from CPU_6x4x / PERIPHCLK may be reported as verified
fact**. It does not block the host-only build — with the watchdog off (§4) nothing in session
1 depends on the value. Recorded in `manifests/l5_manifest.json`
`pinned_at_build.preflight_before_board` and `docs/l5_prereg.md` §4.

## 6. Files (all host-only)

- `firmware/bsp/` — `build.sh`, `lscript.ld`, `include/{xparameters,bspconfig,xmem_config}.h`,
  `src/console.c`. Sources tracked; `firmware/bsp/out/` and `toolchain/` git-ignored.
- `firmware/p3_app.c` — banner updated from "NEVER COMPILED" to "COMPILED, NOT BOARD-RUN";
  `tests/test_firmware_audit.py` updated to assert the new standing. No logic changed.
- `manifests/l5_manifest.json` — `pinned_at_build` complete: toolchain, console UART,
  the embeddedsw BSP input set and `app_image_sha256` pinned; watchdog off with
  `watchdog_load_value` recorded as *not used*; the CPU-clock preflight listed.
- `manifests/l5_bsp_inputs.json` + `host/gen_bsp_input_manifest.py` — the exact Xilinx
  embeddedsw files build.sh compiles into the image (sources + header closure), pinned by
  path/size/sha256. See the reproducibility note below.
- `evidence/l5_build/` — `build_evidence.json` + a tracked copy of `p3_app.map`
  (`host/gen_build_evidence.py`): the post-build provenance in one place — git state,
  toolchain sha, BSP-input-manifest sha, linker-map sha, image sha (reproduced
  byte-identical), and a pointer to the fail-closed test report.

**Reproducibility, and its one remaining limit (reviewer 2026-08-31).** The compiler is
pinned by sha256; the BSP sources build.sh compiles are now pinned too, in
`manifests/l5_bsp_inputs.json` — every Xilinx `embeddedsw` file the pinned toolchain reads
(`standalone_v9_4` + `scuwdt_v2_6`, sources **and** their header closure, 65 files),
identified by path/size/sha256. The list is not hand-written: `host/gen_bsp_input_manifest.py`
takes it from the compiler's own `gcc -M` dependency output, and
`tests/test_bsp_inputs_manifest.py` re-hashes every entry against the tree on this host and
guards it against build.sh drift. So `app_image_sha256` is now reproducible against an
**identified** input set — those exact files (checked by sha256) plus the pinned toolchain
reproduce the image byte-for-byte (verified: rebuilt → `7540239f…`).

The one limit that remains: those files are still **referenced in place**, not vendored into
the repo, because they are third-party vendor sources under a separate licence
(`docs/import_manifest.md`, "Deliberately NOT imported"). The repo is therefore not
self-contained — a rebuild needs the 2025.2 `embeddedsw` tree present — but it is no longer
reproducible only against "whatever tree this host happens to have": the manifest pins which
tree. Vendoring would remove even that dependency but requires a licence review, and is not
required for session 1.
