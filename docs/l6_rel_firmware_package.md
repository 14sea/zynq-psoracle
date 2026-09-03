# L6 rel-v4 firmware batch — delivery package for the full P3 compatibility review (2026-09-03)

> **Standing (2026-09-03, final): the full P3 compatibility review of this package = HOLD
> (owner; §7 — the first candidate `734d6c04…` withdrawn DEFECTIVE, must not run); the short
> re-review of §7 = the three fixes PASS, HOLD on evidence closure (§8, the process record);
> the evidence-closure review of §8 = PASS (owner 2026-09-03; `6c72db9`, `b3806ad`, `57cc22b`
> pushed). The corrected image `5deee74c…` (§7) was then PROMOTED to `pinned_at_build` in
> `manifests/l6_manifest.json` (protocol rel-v4, `board_ready: true`) by the owner's
> promotion/freeze batch of 2026-09-03, and the v0.6 preregistration frozen with it;
> `403f4ab5…` (rec-v3) is superseded, NOT defective, its C1 #5 HOLD kept under v0.4. The
> promoted image has not run on hardware. §0–§6 describe the batch as delivered and are kept
> as the review's object, with the hashes updated to the corrected image; §7 and §8 are the
> review records. No ruling, no board contact; the stop-loss stays TRIGGERED.**

## 0. The owner's mandatory deliverables and where each lands

| deliverable (owner, 2026-09-03) | where | proof |
|---|---|---|
| IDENT 1.3.0 with the `sign_retry_control` bit5 echo | `firmware/p3_wire.c` (`schema_version 1.3.0`, `sign_retry_control` sorted after `schema_version`), `p3_app.c` (`S.sign_control` from `P3_SIGNTX_CONTROL_FLAG` = flags.bit5, echoed in `establish_identity`) | `tests/test_firmware_rel_contract.py::test_ident_one_transmission_one_ack` (the C bytes pass `check_l6_identity(..., rec_retry_control=True, sign_retry_control=True)`), `test_firmware_rel_audit::Identity`, `test_firmware_wire_contract::test_identity_1_1_carries_the_three_l6_fields` (updated) |
| the five poll-count bounds pinned: source audit, C twin, manifest pin | `p3_app.c` `P3_IDENT_IDLE_POLLS`, `P3_SIGN_IDLE_POLLS`, `P3_PULL_IDLE_POLLS`, `P3_REC_IDLE_POLLS`, `P3_TERM_IDLE_POLLS`; `manifests/l6_manifest.json` `next_image.bound_contract.poll_caps`; the twin's timed receiver with an injected clock | `test_firmware_rel_audit::BoundContract::test_every_poll_cap_named_by_the_contract_exists`; `host/l6_rel.FIRMWARE_BOUND_CONTRACT["applies_to"]` names the same five |
| **proof that every board bound ≤ 10 s on the pinned clock** (host timing of the twin is not it) | every wait is `recv_line_bounded` → `p3_rectx_recv_line_timed` with the global timer (`XTime_GetTime`) as clock and `P3_BOUND_TICKS` = `P3_BOUND_S` (8) × `COUNTS_PER_SECOND`; the first of the clock bound and the poll cap to run out ends the wait; `COUNTS_PER_SECOND` = `XPAR_CPU_CORTEXA9_0_CPU_CLK_FREQ_HZ / 2` = 333,333,343 Hz on the pinned 6:2:1 clock (`CPU_CLK_CTRL` 0x1f000200, verified per session by the runner); the timer started once at `go` (`XTime_SetTime(0)`) and read-only afterwards; the poll caps are a termination backstop, not the proof | `test_firmware_rel_audit::BoundContract` (5): the receiver's clock branch in the source, the number derived from the pinned clock (8.0 s ≤ 10.0 s), one clock read site, no blocking receive left, the timer started once before `establish_identity`. **Conditional on the pinned clock**, which the runner checks on the board every session; nothing here measures the target. |
| C twins for the IDENT refusal, the AUDITWAIT counts, the CLOSE/TERM redundancy | `firmware/p3_wire_twin.c` `identtx`, `signtx`, `termtx`, `pulltx` (the board's `p3_tx_run` / `p3_pull_run` over a pipe, every host line through the board's timed receiver with an injected clock); the `term` command carries `closing_control` | `RelContract::test_the_real_ident_host_refuses_and_the_board_exhausts` (the real `IdentHost` refuses, no ack, STOP_IDENT after 3), `test_a_lost_done_draws_auditwait_and_the_replayed_done_completes_the_pull`, `test_three_unanswered_waits_give_the_audit_up`, `test_term_ack_get_bound_and_exhaustion` (`closing_from_term` on the C bytes), `test_a_stopped_epochs_term_carries_no_closing_control` |
| two from-scratch byte-identical builds | `rm -rf firmware/bsp/out; IMAGE=p3_app_l6 bash firmware/bsp/build.sh` twice | corrected image (§7): bin `5deee74c44785ebe88168ccffaa5f399f26a7c5a567fccb3d430cf4eb14cdc7c` (98 324 B), ELF `ebe97ce6a591bad652f373ea6ac4b8591d189966e725234c43507bf66cf0067c`, identical both times; `evidence/l6_next_build/build_evidence.json` (`reproduced_byte_identical: true`, cites the green report), `p3_app_l6.map`. The withdrawn first candidate: bin `734d6c04…`, ELF `a2a42215…`, record kept as `build_evidence_734d6c04.json` / `p3_app_l6_734d6c04.map` |
| `next_image`, `board_ready: false`, then the full P3 compatibility review | `manifests/l6_manifest.json` `next_image` (hashes, protocol `rel-v4`, standing, `wire`, `bound_contract`) | `tests/test_package_consistency.py`, `tests/test_bsp_inputs_manifest.py` (the same 65 BSP inputs) |

## 1. What changed on the board, item by item (prereg v0.6 draft §2.6i–6p)

| § | change | file | twin / test |
|---|---|---|---|
| 6i | the wire protocol is rel-v4; the IDENT declares it | `p3_app.c` `in.protocol = "rel-v4"` | `RelContract::test_ident_one_transmission_one_ack` |
| 6j | **IDENT handshake before any SIGNREQ**: `establish_identity` builds the IDENT once and runs `p3_tx_run` (ack IDENTACK, no re-request, ≤ 3 transmissions on the bound); exhaustion → `STOP_IDENT`, TERM, no candidate; a refusal by the board's own checks still runs the handshake, then stops | `p3_app.c` `establish_identity`; `main` (identity first, `emit_summary` on failure) | `identtx`: clean; lost → resent (same bytes); 3 losses → STOP_IDENT; the real `IdentHost` refusing → STOP_IDENT; a torn ack → partial, resend |
| 6k | **the SIGNREQ transaction**: the line built once (`g_tx_line`), `p3_tx_run` with ack SIGNOK/SIGNREF, re-request SIGNGET, ≤ 3; the strict rule — a RECACK/RECGET naming the previous record skipped (≤ 8), any other acknowledgement PROTOCOL; exhaustion → the terminal `STOP_SIGN` record (`sign_stop {attempts, why}`, verified replayed-only, no ARM, no nonce) then the stop; `audit_requested` read from the SIGNOK payload — **no AUDITREQ frame**; the seq-1 control on flags.bit5 corrupts attempt 1's CRC | `p3_app.c` `run_candidate`; `p3_rectx.c` `p3_tx_run` (`prev_strict`, `P3_RECTX_PREV_ACK_LIMIT` 8); `p3_wire.c` `sign_stop` | `signtx`: SIGNOK / SIGNREF; SIGNGET + the bound resend identical bytes; exhaustion STOP_SIGN; the control corrupts attempt 1 only; previous ack skipped, another seq's PROTOCOL, the 9th stale PROTOCOL; the real `SignHost` + `NotaryRelay`: one signature, cached replay, SIGNGET; `rec … outcome=STOP_SIGN` validates |
| 6l | **AUDIT_READY resent** on the bound while no GET was seen, ≤ 3 | `p3_pull.c` (`P3_PULL_READY_ATTEMPTS`); `p3_app.c` keeps the READY line (`g_ready_line`) and resends it verbatim | `pulltx`: lost READY resent (same bytes); three → given up ("never asked") |
| 6m | **AUDITWAIT** after the last chunk when DONE did not arrive, ≤ 3, the host's replayed DONE completes the pull; exhaustion gives the audit up as before. **§7:** a DONE before every chunk was served aborts the pull (no `done`, no `audited`, no ARM); `served` = unique chunks (popcount of `served_mask`) | `p3_pull.c` (`P3_PULL_WAIT_MAX`, `served_mask`, `all_served`, `popcount`); `p3_app.c` `pull_send_wait_cb`; `p3_wire.c` `p3_wire_audit_wait` | `pulltx` with the real `PullHost`: DONE lost → AUDITWAIT {served 8} → `on_wait` replays → done; three unanswered → aborted; DONE with 0 and with 7/8 chunks → aborted; a repeated GET → `served 8`, `gets 9` |
| 6n | **indexed heartbeats**: `HB` carries `{"i": k}`, k restarting at 0 for every record | `p3_app.c` `heartbeat` (`S.hb_i++`), `p3_wire.c` `p3_wire_hb` | `RelContract::test_the_indexed_heartbeat…`; `test_firmware_rel_audit::Heartbeats` |
| 6o | **TERM transaction** (TERMACK / TERMGET, ≤ 3, then halt) carrying the **closing control** (`closing_control {fault, kind, status, nonce_before, nonce_after}` exactly when the control was reached — `closing.unsigned_control == done`) | `p3_app.c` `emit_summary`, `closing_unsigned_control` (keeps the fields); `p3_wire.c` summary | `termtx`: ACK; TERMGET resend identical; the bound; exhaustion halts; the real `TermHost` acks and re-acks; a STOPPED epoch's TERM carries no block; `closing_from_term` reconstructs from the C bytes |
| 6p | **every wait the timed receiver** (`p3_rectx_recv_line_timed`: idle bound = polls AND ticks; the whole-line bound = 4× the polls but **the SAME ticks** (§7 — it was 4× the ticks, 32 s, in `734d6c04…`); the count-only form is the timed one with no clock); the blocking L5 `recv_line` is gone | `p3_rectx.c`, `p3_app.c` `recv_line_bounded` / `app_now_ticks` | `test_firmware_rel_audit::BoundContract` (`line_ticks = idle_ticks`, worst path ≤ 10 s); `RelContract::test_a_torn_ack_is_partial…`, `test_2_a_trickled_line_is_abandoned…` |

Unchanged and re-audited: the settle poll, the serialiser tally, the audit words and their
sparse encoding, the MMIO allowlists (`tests/test_axi_map_vs_rtl.py`), the DMA order, no
ICAPE2, no SLCR write (the global timer is an SCU private peripheral, started once), the
watchdog's flag gating, the REC transaction (now `p3_rectx_run` = `p3_tx_run` with
RECACK/RECGET), the two operators and their twins. `tests/test_firmware_audit.py` (63)
runs green on the new source with its anchors updated to the new structure
(`build_payload_frame("IDENT"`, the timed receiver, the pure units' strings).

## 2. Build

`IMAGE=p3_app_l6 bash firmware/bsp/build.sh` (the pinned xPack arm-none-eabi-gcc 14.2.1,
the hand-assembled Cortex-A9 BSP from the same 65 embeddedsw files as before —
`manifests/l6_bsp_inputs.json` unchanged; `p3_pull.c` added to the application's source
list). Two builds from `rm -rf firmware/bsp/out`: identical `p3_app_l6.bin` (sha256
`5deee74c…`, 98 324 B; the withdrawn first candidate was `734d6c04…`) and `p3_app_l6.elf`
(`ebe97ce6…`). No compiler warning from the
application sources (`-Wall -Wextra`); the twin builds with `-Werror -pedantic`.

## 3. Host side unchanged in behaviour, wired for the image

The host implements rel-v4 already (`host/l6_rel.py`, the ConsoleSession switch, the
validator's STOP_SIGN and rule vii-b, the §6.10–13 gates); the runner selects it by the
pinned image's protocol and refuses a prereg/image protocol mismatch — so this image runs
under NO current pin: `pinned_at_build` is rec-v3 and the frozen prereg is v0.4.
Promotion (owner) → `pinned_at_build.protocol = rel-v4` → the v0.6 text frozen (its
`prereg.protocol = rel-v4`) → rulings.

## 4. What is NOT claimed

- Nothing about the board: the image has not run; the bound proof is conditional on the
  pinned clock, which the runner verifies from `CPU_CLK_CTRL` before every session;
  target timing has not been measured.
- Nothing about the physical console path.
- The twin's injected clock exercises the receiver's logic; it is not a wall-time
  measurement and is not presented as one.

## 5. Tests

`bash host/run_tests.sh` — the report cited in `evidence/l6_next_build/build_evidence.json`
and in the commit: 1014 tests / 1 skip / rc 0 (`evidence/tests/test_report_2026-09-03T095145Z.json`; the run before it, `…095029Z`, failed on one stale allowance in `tests/test_package_consistency.py` and is kept as recorded) (the first candidate's package cited
1009 / 1 / 0). New: `tests/test_firmware_rel_contract.py` (21 — 17 + the four of §7),
`tests/test_firmware_rel_audit.py` (12). Updated: `tests/test_firmware_audit.py`
(14 anchors), `tests/test_firmware_wire_contract.py` (the identity test), `tests/test_l6_rel.py`
(39, the Python early-DONE refusal).

## 6. Asked of the owner

1. ~~The full P3 compatibility review of this package~~ — done 2026-09-03: HOLD (§7).
2. ~~The short re-review of §7 (host-only, scoped: no board)~~ — done 2026-09-03: the three
   fixes PASS, HOLD on evidence closure (§8); the evidence-closure review = PASS.
3. ~~On PASS: promotion of `5deee74c…` to `pinned_at_build` (rec-v3 `403f4ab5…` superseded,
   not defective, its C1 #5 evidence kept), the freeze of the v0.6 text~~ — done 2026-09-03
   (the owner's promotion/freeze batch, host-only); still open: the frozen-artifact short
   review, then the ruling on the stop-loss (TRIGGERED; a conditional lifting opens at most
   ONE rel-v4 C1) and the first rel-v4 C1 ruling pair.

## 7. Re-review record (2026-09-03): the three findings and the corrected image

The owner's full P3 compatibility review of `734d6c04…` (commit `6c72db9`, not pushed):
**HOLD** — no push, no promotion, no freeze, no ruling, no board. `734d6c04…` is withdrawn
**DEFECTIVE — must not run** (`manifests/l6_manifest.json` `pinned_at_build.withdrawn_images`,
third entry, with its ELF hash and the three findings); its build record is preserved as
`evidence/l6_next_build/build_evidence_734d6c04.json` + `p3_app_l6_734d6c04.map`.

| # | finding (owner) | fix | discrimination test (fails on the withdrawn source, passes now) |
|---|---|---|---|
| **B1** | `p3_pull.c` accepted an `AUDITDONE` with zero or partial chunks served — the host's DONE was taken as completion whatever had been served, so an incomplete audit could be marked `audited` and reach ARM; Python `PullBoard` the same | `p3_pull.c`: `AUDITDONE` is accepted only when `all_served` (every bit of `served_mask` below `chunks`); otherwise the pull is aborted fail-closed — `aborted 1`, `done 0`, `why` "AUDITDONE before every chunk was served: the audit is not complete" — and `p3_app.c` takes its existing abort path (no `audited`, no ARM on the SCORED path, `STOP_AUDIT`). `host/l6_audit_pull.py` `PullBoard.on_host_line`: DONE before every chunk → `_abort()`, `finish()` = `STOP_AUDIT`, `audited` false | `RelContract::test_1_a_done_before_every_chunk_was_served_gives_the_audit_up` (C: DONE after 0 chunks → `rc -1 done 0 aborted 1 gets 0 mask 0`; after 7/8 → `mask 127`, aborted, the why); `test_1_the_python_twin_refuses_the_same_early_done` and `test_l6_rel::ReadyAndDone::test_a_done_before_every_chunk_is_refused_by_the_twin` (Python: `ABORTED`, `STOP_AUDIT`, not `audited`) |
| **B2** | the whole-line wall-time bound was `idle_ticks × P3_RECTX_LINE_POLL_FACTOR` = 4 × 8 s = 32 s: a host line trickled in below the idle gap could hold the application 32 s against the 10 s host contract | `p3_rectx.c`: `line_ticks = idle_ticks` — the idle gap AND the whole line share the one tick bound, so a receive ends within `P3_BOUND_S` = 8 s on the pinned clock however the bytes are paced; the ×4 factor remains on the poll count only (the termination backstop for a timer that does not advance). `host/l6_rel.FIRMWARE_BOUND_CONTRACT["whole_line"]` and the manifest's `bound_contract.whole_line` pin it | source-derived: `test_firmware_rel_audit::BoundContract` asserts `const uint64_t line_ticks = idle_ticks;`, the absence of `idle_ticks * P3_RECTX_LINE_POLL_FACTOR`, the byte-branch check `t_last - t_start > line_ticks`, and max(idle, whole-line) = 8.0 s ≤ 10.0 s; injected clock: `RelContract::test_2_a_trickled_line_is_abandoned_within_the_same_bound_as_the_idle_gap` — the twin's `!trickle 60 aaaaaaaaaa` (11 bytes, 60 empty polls before each = 660 ticks, never exceeding the 300-tick idle gap) is abandoned as PARTIAL and the IDENT resent (`attempts 2 partial 1 stale 1`); under the withdrawn source (1200 ticks) it was accepted as a line; `!trickle 10` (110 ticks) is still a line (`partial 0 stale 1`) |
| **C** | `AUDITWAIT.served` counted transmissions (`chunks_served`), not unique chunks; a re-served chunk made it exceed `chunks` | `p3_pull.c`: `send_wait(popcount(served_mask))` — in the all-served branch this equals `chunks` by construction | `RelContract::test_3_auditwait_served_counts_unique_chunks_not_transmissions`: chunk 0 requested twice, DONE withheld → AUDITWAIT `served 8` (the withdrawn source said 9) while the result says `gets 9 served 9` (transmissions, reported separately) |
| — | the contradictory `next_prereg.status` sentence in the manifest ("pending the full P3 compatibility review; frozen only after that review passes, the firmware batch has built …") | rewritten: the review is recorded as HOLD with its three findings; the draft is frozen only after the re-review passes and the image is promoted | `tests/test_package_consistency.py` (the withdrawn list now `47b8fa09, cd8360dc, 734d6c04`) |

The twin's clock model changed with B2: it ticks on EMPTY polls only (a waiting byte costs
no time — on the board a whole line arrives back-to-back in milliseconds against an 8 s
bound), so a long host line (a SIGNOK with its signature is > 300 bytes) is never cut by
the twin's 300-tick bound and the two bounds are exercised only by the gaps a test injects
(`!idle`, `!trickle N`). This is the host twin's model, not the image: the image's clock is
the global timer, and the source audit is the proof. `firmware/p3_app.c` and `p3_wire.c`
are unchanged from `734d6c04…`; the image differs only by `p3_pull.c` and `p3_rectx.c`.

Two from-scratch builds byte-identical: bin
`5deee74c44785ebe88168ccffaa5f399f26a7c5a567fccb3d430cf4eb14cdc7c` (98 324 B), ELF
`ebe97ce6a591bad652f373ea6ac4b8591d189966e725234c43507bf66cf0067c` → `next_image`,
`board_ready: false`; `evidence/l6_next_build/build_evidence.json` regenerated for it and
cites the green report. Not run on hardware. The stop-loss stays triggered; C1 #5 stays HOLD
under v0.4; no push, no freeze, no ruling, no board.

## 8. Evidence-closure record (2026-09-03): the short re-review of §7

The owner's short re-review of §7: the three technical fixes **PASS** (B1 at `p3_pull.c`
`all_served`, and `PullBoard`; B2 `line_ticks = idle_ticks`, ≈ 8 s idle and whole-line on
the pinned timer, the `!trickle 60` / `!trickle 10` discrimination confirmed; C `served` =
popcount — `gets 9 served 8 mask 255` reproduced); the image and the live build evidence
**PASS** (bin `5deee74c…`, ELF `ebe97ce6…`, map `a0dab213…` on disk = manifest = evidence;
1014 OK in the owner's environment with one more boundary skip, an environment difference).
Still **HOLD** on one narrow evidence-closure blocker — no push, no promotion, no freeze,
no ruling, no board; no firmware change, no rebuild.

| finding (owner) | correction |
|---|---|
| `build_evidence_734d6c04.json` recorded the map hash `4d07230f…` but pointed `linker_map.path` at the directory's LIVE `p3_app_l6.map` (now `a0dab213…`, the new image's); the archived map `p3_app_l6_734d6c04.map` is the one that hashes `4d07230f…` | every archived record's `linker_map.path` now names its archived map — not only `734d6c04`'s: the same defect was in **all five** archived records (`l6_next_build`: `734d6c04`, `cd8360dc`, `e19e1b12`; `l6_build`: `bd1454cd`, `e19e1b12`), each pointing at the live map of its directory |
| the same record's `image.bin` pointed at `firmware/bsp/out/p3_app_l6.bin`, which every build overwrites and which cannot verify back to `734d6c04…` | the withdrawn/superseded binaries are not preserved (out/ is gitignored and rebuilt), so `image.bin` in every archived record is now the explicit marker `historical artifact unavailable — hash-only: …` and never a live path; `bin_sha256` / `elf_sha256` unchanged. Each archived record gained an `archived` block: the date, why, the original two paths, the archived map, `hashes_unchanged: true` |
| §7 claimed the old build record and map were "preserved", so the live path was a substantive defect, not wording | §7's claim now holds by construction: the record names the archived map and says the binary is hash-only |
| `tests/test_package_consistency.py` checked the exact withdrawn list only inside the `next_image is None` branch — with a candidate pinned, the guard did not run | `test_one_image_one_authority`: the exact superseded and withdrawn sets, `board_ready`, the rec-v3 pin and the promotion note are asserted on BOTH branches; with a candidate it additionally asserts the candidate is not withdrawn and that the live next-build evidence (bin and ELF) is the candidate's |
| (requested) a fail-closed test: every archived record's non-empty artifact path exists and hashes | new `BuildEvidenceClosure` (5 tests) over every `evidence/*/build_evidence*.json` (8 records: 3 live, 5 archived): `linker_map.path` exists and hashes; a cited test report exists and hashes (when a `report_sha256` is recorded — `l5_build`'s older schema has none); `image.bin` either hashes on disk (live records; absent `out/` is tolerated for the live record only, as before) or is the hash-only marker with an `archived` block — an archived record naming a live path FAILS; archived records are named by their image and name their archived map |

The closure test also caught the LIVE record of the board-ready pin,
`evidence/l6_build/build_evidence.json` (`403f4ab5…`): its `image.bin` pointed at
`firmware/bsp/out/p3_app_l6.bin`, which HEAD now builds as the candidate `5deee74c…` — the
same class of defect. No `403f4ab5…` binary exists on disk (searched by size and hash), so
that record's `image.bin` is now the hash-only marker with a `binary_unavailable` block
(date, why, the original path, `hashes_unchanged: true`); its map path was already the
directory's own `p3_app_l6.map` (`963dcd0f…`, verified). Nothing about the pin changed:
`pinned_at_build` is `403f4ab5…`, `board_ready: true`; a rec-v3 session would need the
binary rebuilt from the promoted commit, which the runner enforces by hash before loading.

`evidence/` edits are limited to the six JSON records' path fields plus the added
`archived` / `binary_unavailable` blocks; no hash changed, no map or report was touched. The manifest and
the image are unchanged (`next_image` `5deee74c…`, `board_ready: false`).


**Final standing of §8 (owner's evidence-closure review, 2026-09-03): PASS.** The five
archived map hashes recomputed equal; the six JSON records' hash fields unchanged against
the parent commit; the historical binaries hash-only; the live next-build BIN / ELF / MAP =
`5deee74c…` / `ebe97ce6…` / `a0dab213…`; the eight closure records closed; the guard on
both branches; 1019 tests (the owner's independent run: OK with one more boundary skip, an
environment difference). Non-blocking note kept: the closure test still lets a
non-archived live record pass when `out/` is absent (the documented exception). The HOLD
recorded above stays as the process record; `6c72db9`, `b3806ad`, `57cc22b` were pushed
(`origin/main` = `57cc22b`). The promotion of `5deee74c…` and the v0.6 freeze followed in
the owner's separate promotion/freeze batch (2026-09-03): `pinned_at_build` = `5deee74c…`
(rel-v4, `board_ready: true`), `403f4ab5…` superseded NOT defective, its record archived as
`evidence/l6_build/build_evidence_403f4ab5.json` + `p3_app_l6_403f4ab5.map`,
`evidence/l6_build/build_evidence.json` regenerated for the promoted image (firmware bytes
unchanged, no rebuild), `docs/l6_soak_prereg.md` = v0.6 (protocol rel-v4, sha pinned in the
manifest). No ruling, no board contact; the stop-loss stays TRIGGERED.
