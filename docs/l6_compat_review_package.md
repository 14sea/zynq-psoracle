# L6 §2 — the two-operator image: P3 compatibility review package (built 2026-09-01, host-only; first review HOLD → corrected image the same day)

> **Standing: host-only. BUILT AND PINNED, NEVER RUN ON HARDWARE.** Authorised by the owner
> on 2026-09-01 after the §4 batch passed its third short review. Boundary kept: no
> ruling, no board contact, no C1/C2/S. This is the whole-package entry point for the P3
> compatibility review the preregistration requires (`docs/l6_soak_prereg.md` §2.7) before
> the owner freezes the preregistration (`manifests/l6_manifest.json` `prereg.sha256`,
> null today) and issues the first board-phase ruling. `host/l6_runner.py` refuses to run
> until that hash is set — by construction, not discipline.

## 1. The image

| | value |
|---|---|
| application image | **`bd1454cd0258c3f998b6cfcc25e982400b63321054db40cde3d790b3b366c8b4`** — `firmware/bsp/out/p3_app_l6.bin`, 98 324 bytes, → `0x0200_0000`, entered with `go` |
| withdrawn | `47b8fa09…` — **DEFECTIVE, must not run**: kicked the watchdog before initialising it (§4.7); never run on hardware; `pinned_at_build.withdrawn_images` |
| ELF | `388601fd431096dfb8de472a3cff0975930b0318e973d7d2f5ef307939ea6178` |
| build | `IMAGE=p3_app_l6 bash firmware/bsp/build.sh` — same script, toolchain, flags, linker script and BSP as L5; only the artefact name differs so the two lines' images cannot be confused on disk |
| reproducibility | two `rm -rf firmware/bsp/out` builds, byte-identical (`evidence/l6_build/build_evidence.json`, `reproduced_byte_identical: true`); the evidence cites its test report explicitly and the generator refuses a non-green one (§4.8) |
| toolchain | xPack `arm-none-eabi-gcc` 14.2.1-1.1, tarball `ed8c7d20…` (L5's pin, unchanged) |
| BSP inputs | `manifests/l6_bsp_inputs.json` — regenerated from `gcc -M` for this build; **the same 65 files, same hashes, as L5's** (`tests/test_bsp_inputs_manifest.py::L6InputsAreTheSameSet`) |
| map data | `firmware/p3_data.h` `P3_OPERATOR_DATA_SHA256 = 0c9c82a8…` = `host/l6_operators.operator_data` over the pinned `local_map.json` (`56f2b9e8…`) + phenotype manifest; `host/gen_firmware_data.py --check` regenerates and compares |
| L5 image | `a7c73d1f…` untouched and still pinned in `manifests/l5_manifest.json`; it is **not** reproducible from this tree's sources (they changed) and its test skips when `out/p3_app.bin` is absent |

## 2. Prereg §2 item by item

| §2 | requirement | where | proven by |
|---|---|---|---|
| 1 | two operators, pure functions of `(master_seed, index)`: random-safe uniform over the 292; map-guided consulting the map (same-LUT); map data compiled in must hash to the pinned `local_map.json` derivation, checked by a host test that regenerates it | `firmware/p3_search.c` (`p3_op_random_safe`, `p3_op_map_guided`), tables in `firmware/p3_data.h` (`P3_LUT_BITS`, `P3_LUT_LEN`, `P3_MUTATION_BITS`, `P3_OPERATOR_DATA_SHA256`) from `host/gen_firmware_data.py` | `tests/test_firmware_twin.py::OperatorTwin` (corpus, forced/abba, header hash), `test_generated_data_header_is_current`, `tests/test_l6_operators.py` (universe == whitelist, reach, locality) |
| 2 | preregistered arm schedule `arm(index)` from the master seed by A,B,B,A; record carries `(seed, arm)` | `p3_arm_abba`, `p3_arm_for` (modes 0/1/2, 3 refused), `p3_pair_seed` = `PAIR_SEED_RULE` | `OperatorTwin::test_arm_schedule_matches_all_three_modes_and_refuses_the_fourth`, `test_pair_seed_matches_the_python_rule` |
| 3 | Python twins + corpus equality N ≥ 256, bit for bit | `host/l6_operators.py`, `host/l6_schedule.py`, `fixtures/l6_operator_corpus_v1.json` (256) | `OperatorTwin::test_whole_corpus_reproduces_arm_seed_and_genome` — arm, pair seed and genome equal on all 256 |
| 4 | record names the arm; IDENT names the master seed and the operator-image identity; validator refuses a swapped arm | `p3_wire.c`: `loop_record` 1.1.0 `arm` (absent on the brackets), `app_identity` 1.1.0 `master_seed` / `schedule_mode` / `operator_data_sha256`; `p3_app.c` wires `rec.arm = arm_name` (NULL for the baselines) and the IDENT fields | `tests/test_firmware_wire_contract.py::L6WireContract` — C bytes through the real collector and validator; `check_arm_schedule` accepts the schedule and refuses a swap; `check_l6_identity` accepts/refuses each field; `tests/test_firmware_audit.py::WireWiring::test_candidates_carry_the_scheduled_arm_and_baselines_none`, `test_the_identity_names_the_master_seed_mode_and_operator_data` |
| 5 | everything else unchanged and re-audited | wire contract, settle poll, serialiser tally, audit service, MMIO allowlists vs RTL, DMA order, no ICAPE2, no SLCR write, flag gating | every pre-existing test in `test_firmware_audit.py` (register discipline, DMA, configuration commands, state machine, settle poll, tally), `test_axi_map_vs_rtl.py`, `test_firmware_wire_contract.py::WireContract` — all still green on the new source |
| 6 | watchdog per D-s1: prescaler 7, load 1 250 000 035 → 30.0 s, kicked at the heartbeat points, gated by `flags.bit1`; bit1 = 0 exactly L5; the build and tests pin the actual load | `p3_app.c`: `P3_WDT_LOAD 1250000035u`, `P3_WDT_PRESCALER 7u`; inside `if (S.page.flags & 2u)`: `LookupConfig` → `CfgInitialize` (NULL / failure → `STOPPED` "the watchdog could not be initialised", TERM, return) → one `XScuWdt_SetControlReg` (prescaler ∥ WD mode) → `LoadWdt` → `Start` → **`S.wdt_started = 1`** as the block's last statement; the kick (after every framed line) is gated on `S.wdt_started`, never on the flag | `test_the_watchdog_is_touched_only_under_the_identity_flag` (call list, order, WD-mode bit, the literal load and prescaler equal to the manifest, nothing outside the gate, no Stop/Disable); **`test_the_kick_never_touches_an_uninitialised_watchdog`** (kick gated on `wdt_started`, IDENT precedes the block, the single assignment is the block's last statement after `Start`, the early-set mutant is caught); `test_watchdog_init_failure_is_fail_closed_with_a_term`; `PinnedL6Image::test_the_watchdog_pins_are_the_d_s1_values` |
| 6a | unconditional audit for non-`SCORED` self-reports, before the record, with or without an `AUDITREQ` | `ensure_audit()` before every `STOP_LINK2` (span streams), `STOP_LINK3`, `STOP_AXI` (post-staging), `STOP_SETTLE`, `STOP_ARM`, `REFUSED_BY_PL` record; `SCORED` audited iff requested | `test_every_candidate_that_staged_is_auditable`, `test_a_post_staging_axi_fault_is_recorded_as_stop_axi_with_its_words`; `L6WireContract::test_a_sampled_session_of_c_records_passes_and_the_two_negatives_fail` (auto-audited `STOP_ARM` at an unsampled seq accepted; words withheld → HOLD naming the seq) |
| 7 | owner's review, hash pinned, document frozen | this package; `manifests/l6_manifest.json` `pinned_at_build.app_image_sha256` set; `prereg.sha256` **null — the owner's step** | `PinnedL6Image::test_the_runner_still_refuses_because_the_prereg_is_not_frozen` |

Also required by the §2 authorisation and delivered: **16 HB per complete SCORED record in
seq and order** — unchanged code, now pinned structurally (`test_exactly_sixteen_heartbeats_per_scored_record`:
1 after the streams + 3 in the envelope loop + 12 in the readback loop = `l6_timing.HB_PER_RECORD`,
each `send_frame("HB", S.seq, "-")`); **`mutation_bits = 4` and the `operator_data_sha256`
contract** (the hash covers the value; the IDENT names it; the S runner refuses a
calibration under another contract); **flags bits 2–3** as the schedule mode (mode 3 is an
identity finding → `STOPPED` before any candidate).

## 3. Changes to the firmware, exhaustively

`firmware/p3_search.c` — replaced (the file the L5 sampler said would be replaced "and nothing else"; the interface gained `mode` and `*arm_out`).
`firmware/p3_data.h` — regenerated: + operator tables and `P3_OPERATOR_DATA_SHA256` (generator extended).
`firmware/p3_wire.h/.c` — `app_identity` 1.1.0 (three fields), `loop_record` 1.1.0 (`arm`).
`firmware/p3_wire_twin.c`, `firmware/p3_twin.c`, `firmware/Makefile` — host drivers only (`p3_search.c` now linked into the derive twin; `pairseed`/`arm`/`candidate` modes).
`firmware/p3_app.c`:
1. `P3_WDT_LOAD 1250000035u`, `P3_WDT_PRESCALER 7u`; the gated arm block: `LookupConfig` → `CfgInitialize` (fail-closed) → one `XScuWdt_SetControlReg` (prescaler 7 ∥ `XSCUWDT_CONTROL_WD_MODE_MASK`) → `LoadWdt` → `Start` → `S.wdt_started = 1`; `kick_watchdog` tests `S.wdt_started` (was: the flag).
2. `schedule_mode()` = `flags` bits 2–3; mode 3 → identity finding "schedule mode 3 is unassigned" (the IDENT is still sent, then `STOPPED`).
3. IDENT: `master_seed = page.seed`, `schedule_mode`, `operator_data_sha256 = P3_OPERATOR_DATA_SHA256`.
4. `run_candidate(genome, is_baseline, arm_name)`; `rec.arm = arm_name`; baselines pass `NULL`; the loop calls `p3_search_next(genome, seed, i, schedule_mode(), &arm)` and `P3_ARM_NAME[arm]`.
5. `ensure_audit(with_readback)` and its six call sites (§2.6a); the `SCORED` path still audits iff requested.
6. `serve_audit` loops while `S.kind != P3_PROTOCOL` (was `== P3_RUNNING`) and sets the mark on the same condition — see §4.1.
7. The pre-ARM fault path (`arm_attempt` → −1) now emits a `STOP_AXI` record with the oracle self-report, auto-audited (was: no record).

Nothing else. In particular: no new `Xil_In32`/`Xil_Out32` target, no SLCR access beyond the IDCODE read, the four DMA tuples, the settle poll, the tally, the CTRL-is-write-only stance, the cache attributes — all unchanged and still under the same tests.

## 4. Findings made while building (for the review's attention)

1. **The L5 image could never serve a link-2 refusal's words.** In `run_candidate` the `STOP_LINK2` path called `p3_stop(P3_STOPPED, …)` *before* `serve_audit(0)`, and `serve_audit`'s loop ran only while `S.kind == P3_RUNNING` — so zero chunks were sent and the record went out `replayed-only`, which the all-self-reporting policy would have refused as a HOLD. No L5 session hit a link-2 refusal, so it never showed. Fixed here (words first, loop gated on `P3_PROTOCOL` only) and pinned by `test_serving_survives_a_stop_but_not_a_channel_failure`. It does not touch L5's PASS (no session took that path) and is recorded as a latent defect of `a7c73d1f…`, not a withdrawal.
2. **Audit placement on the ARM-failure paths.** For `STOP_SETTLE`/`STOP_ARM`/`REFUSED_BY_PL`/post-staging `STOP_AXI` the words are served *after* the ARM (the outcome is only known then), so the frame order for those records is `HB`×16 → `REC`-preceding `AUDIT`×8 → `REC`, which the timing breakdown attributes to `audit` + `arm_settle_score` jointly (the `SCORED` order, `HB`×16 → `AUDIT`×8 → `REC`, is unchanged, so the calibration's breakdown is unaffected).
3. **`STOP_AXI` before the sign reply cannot be a record** (the schema needs `sign_reply`); an AXI fault there ends the epoch with no record and shows up as the structural `missing REC` HOLD, as before. Only the post-staging pre-ARM fault gained a record.
4. **The TERM's `drop_budget` is the firmware constant 16**, not the D-s4 session budget (the identity page has no spare word). The budget that ends the epoch is the host relay's (D-s4, the authority); the TERM's number is informational and the validator's `crc_dropped > drop_budget ⇒ PROTOCOL` check still holds. Recorded rather than hidden; a page-layout change would be a bigger edit than the value warrants.
5. **What the watchdog does on timeout is board-observable only.** Watchdog (reset) mode asserts the A9 watchdog reset request; which reset the SLCR routes it to (`RS_AWDT_CTRL`, unread — no SLCR read is permitted beyond the IDCODE) decides whether the collector sees a U-Boot banner or silence; either is `CRASHED`. The first session with `flags.bit1 = 1` is the first observation of it.
6. The linker warns `LOAD segment with RWX permissions` — as for L5's build; unchanged linker script.
7. **First review, blocker 1 — the watchdog was kicked before it was initialised.**
   `main()` calls `establish_identity()`, which emits IDENT, and every `send_frame` kicks;
   the kick was gated on `flags.bit1` alone, while `CfgInitialize` ran only after
   `establish_identity()` returned — so with bit1 = 1 the IDENT frame's kick restarted an
   instance with `BaseAddr` 0 and `IsReady` unset, and the driver's assert waits forever:
   the image would have hung after IDENT, before the opening baseline. My tests had not
   caught the cross-function ordering (the owner's 56 targeted tests confirmed the gap).
   Image `47b8fa09…` is withdrawn as DEFECTIVE, must not run. Fix: `S.wdt_started`, set
   only as the last statement of the init block after `Start`; the kick tests it and nothing
   else; `LookupConfig`/`CfgInitialize` failure is fail-closed (`STOPPED`, TERM, return).
   `test_the_kick_never_touches_an_uninitialised_watchdog` pins the order and catches the
   early-set mutant. Rebuilt: `bd1454cd…`, two from-scratch builds byte-identical.
8. **First review, blocker 2 — the build evidence cited a stale test report.** The
   generator took the newest file name (an older green run from before the §2 sources
   changed) and would have cited a red one as readily. Now `gen_build_evidence.py` cites
   a named report (`--report`), reads it, and refuses unless `exit_status == 0` with no
   failures or errors; the evidence records the report's sha256, count, head and result
   line. Report **A** = `evidence/tests/test_report_2026-09-01T132037Z.json` (627 OK, 1 skip) is the
   green run on the corrected tree with the evidence in its `pending` state; the evidence
   then cites A; report **B** = `evidence/tests/test_report_2026-09-01T132048Z.json` (627 OK,
   1 skip) is the run over the final evidence; the package stands on B. The one skip is
   the L5 built-binary comparison (`out/` holds the L6 image; the L5 binary is not
   reproducible from this tree by design).

## 5. Not done, by the boundary

No ruling requested, no board contact, no C1/C2/S, no prereg freeze (`prereg.sha256` null), no change to `manifests/l5_manifest.json` or any evidence directory. The image has never run: every statement above is host-side.
