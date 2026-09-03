# L6 rel-v4 firmware batch — delivery package for the full P3 compatibility review (2026-09-03)

> **Standing: delivered, NOT reviewed. The image `734d6c04…` is `next_image` in
> `manifests/l6_manifest.json` with `board_ready: false`; it has NEVER run on hardware.
> No freeze, no ruling, no board contact: the owner's fourth review (2026-09-03) opened
> this batch with mandatory deliverables and withheld all three until this package passes
> the full P3 compatibility review. `403f4ab5…` (rec-v3) stays `pinned_at_build`; the
> pinned rec-v3 image and the frozen v0.4 text are untouched.**

## 0. The owner's mandatory deliverables and where each lands

| deliverable (owner, 2026-09-03) | where | proof |
|---|---|---|
| IDENT 1.3.0 with the `sign_retry_control` bit5 echo | `firmware/p3_wire.c` (`schema_version 1.3.0`, `sign_retry_control` sorted after `schema_version`), `p3_app.c` (`S.sign_control` from `P3_SIGNTX_CONTROL_FLAG` = flags.bit5, echoed in `establish_identity`) | `tests/test_firmware_rel_contract.py::test_ident_one_transmission_one_ack` (the C bytes pass `check_l6_identity(..., rec_retry_control=True, sign_retry_control=True)`), `test_firmware_rel_audit::Identity`, `test_firmware_wire_contract::test_identity_1_1_carries_the_three_l6_fields` (updated) |
| the five poll-count bounds pinned: source audit, C twin, manifest pin | `p3_app.c` `P3_IDENT_IDLE_POLLS`, `P3_SIGN_IDLE_POLLS`, `P3_PULL_IDLE_POLLS`, `P3_REC_IDLE_POLLS`, `P3_TERM_IDLE_POLLS`; `manifests/l6_manifest.json` `next_image.bound_contract.poll_caps`; the twin's timed receiver with an injected clock | `test_firmware_rel_audit::BoundContract::test_every_poll_cap_named_by_the_contract_exists`; `host/l6_rel.FIRMWARE_BOUND_CONTRACT["applies_to"]` names the same five |
| **proof that every board bound ≤ 10 s on the pinned clock** (host timing of the twin is not it) | every wait is `recv_line_bounded` → `p3_rectx_recv_line_timed` with the global timer (`XTime_GetTime`) as clock and `P3_BOUND_TICKS` = `P3_BOUND_S` (8) × `COUNTS_PER_SECOND`; the first of the clock bound and the poll cap to run out ends the wait; `COUNTS_PER_SECOND` = `XPAR_CPU_CORTEXA9_0_CPU_CLK_FREQ_HZ / 2` = 333,333,343 Hz on the pinned 6:2:1 clock (`CPU_CLK_CTRL` 0x1f000200, verified per session by the runner); the timer started once at `go` (`XTime_SetTime(0)`) and read-only afterwards; the poll caps are a termination backstop, not the proof | `test_firmware_rel_audit::BoundContract` (5): the receiver's clock branch in the source, the number derived from the pinned clock (8.0 s ≤ 10.0 s), one clock read site, no blocking receive left, the timer started once before `establish_identity`. **Conditional on the pinned clock**, which the runner checks on the board every session; nothing here measures the target. |
| C twins for the IDENT refusal, the AUDITWAIT counts, the CLOSE/TERM redundancy | `firmware/p3_wire_twin.c` `identtx`, `signtx`, `termtx`, `pulltx` (the board's `p3_tx_run` / `p3_pull_run` over a pipe, every host line through the board's timed receiver with an injected clock); the `term` command carries `closing_control` | `RelContract::test_the_real_ident_host_refuses_and_the_board_exhausts` (the real `IdentHost` refuses, no ack, STOP_IDENT after 3), `test_a_lost_done_draws_auditwait_and_the_replayed_done_completes_the_pull`, `test_three_unanswered_waits_give_the_audit_up`, `test_term_ack_get_bound_and_exhaustion` (`closing_from_term` on the C bytes), `test_a_stopped_epochs_term_carries_no_closing_control` |
| two from-scratch byte-identical builds | `rm -rf firmware/bsp/out; IMAGE=p3_app_l6 bash firmware/bsp/build.sh` twice | bin `734d6c04895e81d5fef3196f7b3298d03a7c6c6d3b9fe3f35abc9cc0b1e323b1` (98 324 B), ELF `a2a422157aaf1f666a46fc8088b2cf54a68fcb77cecf886f2d7bb8bf4c0b8355`, identical both times; `evidence/l6_next_build/build_evidence.json` (`reproduced_byte_identical: true`, cites the green report), `p3_app_l6.map` |
| `next_image`, `board_ready: false`, then the full P3 compatibility review | `manifests/l6_manifest.json` `next_image` (hashes, protocol `rel-v4`, standing, `wire`, `bound_contract`) | `tests/test_package_consistency.py`, `tests/test_bsp_inputs_manifest.py` (the same 65 BSP inputs) |

## 1. What changed on the board, item by item (prereg v0.6 draft §2.6i–6p)

| § | change | file | twin / test |
|---|---|---|---|
| 6i | the wire protocol is rel-v4; the IDENT declares it | `p3_app.c` `in.protocol = "rel-v4"` | `RelContract::test_ident_one_transmission_one_ack` |
| 6j | **IDENT handshake before any SIGNREQ**: `establish_identity` builds the IDENT once and runs `p3_tx_run` (ack IDENTACK, no re-request, ≤ 3 transmissions on the bound); exhaustion → `STOP_IDENT`, TERM, no candidate; a refusal by the board's own checks still runs the handshake, then stops | `p3_app.c` `establish_identity`; `main` (identity first, `emit_summary` on failure) | `identtx`: clean; lost → resent (same bytes); 3 losses → STOP_IDENT; the real `IdentHost` refusing → STOP_IDENT; a torn ack → partial, resend |
| 6k | **the SIGNREQ transaction**: the line built once (`g_tx_line`), `p3_tx_run` with ack SIGNOK/SIGNREF, re-request SIGNGET, ≤ 3; the strict rule — a RECACK/RECGET naming the previous record skipped (≤ 8), any other acknowledgement PROTOCOL; exhaustion → the terminal `STOP_SIGN` record (`sign_stop {attempts, why}`, verified replayed-only, no ARM, no nonce) then the stop; `audit_requested` read from the SIGNOK payload — **no AUDITREQ frame**; the seq-1 control on flags.bit5 corrupts attempt 1's CRC | `p3_app.c` `run_candidate`; `p3_rectx.c` `p3_tx_run` (`prev_strict`, `P3_RECTX_PREV_ACK_LIMIT` 8); `p3_wire.c` `sign_stop` | `signtx`: SIGNOK / SIGNREF; SIGNGET + the bound resend identical bytes; exhaustion STOP_SIGN; the control corrupts attempt 1 only; previous ack skipped, another seq's PROTOCOL, the 9th stale PROTOCOL; the real `SignHost` + `NotaryRelay`: one signature, cached replay, SIGNGET; `rec … outcome=STOP_SIGN` validates |
| 6l | **AUDIT_READY resent** on the bound while no GET was seen, ≤ 3 | `p3_pull.c` (`P3_PULL_READY_ATTEMPTS`); `p3_app.c` keeps the READY line (`g_ready_line`) and resends it verbatim | `pulltx`: lost READY resent (same bytes); three → given up ("never asked") |
| 6m | **AUDITWAIT** after the last chunk when DONE did not arrive, ≤ 3, the host's replayed DONE completes the pull; exhaustion gives the audit up as before | `p3_pull.c` (`P3_PULL_WAIT_MAX`, `served_mask`); `p3_app.c` `pull_send_wait_cb`; `p3_wire.c` `p3_wire_audit_wait` | `pulltx` with the real `PullHost`: DONE lost → AUDITWAIT {served 8} → `on_wait` replays → done; three unanswered → aborted |
| 6n | **indexed heartbeats**: `HB` carries `{"i": k}`, k restarting at 0 for every record | `p3_app.c` `heartbeat` (`S.hb_i++`), `p3_wire.c` `p3_wire_hb` | `RelContract::test_the_indexed_heartbeat…`; `test_firmware_rel_audit::Heartbeats` |
| 6o | **TERM transaction** (TERMACK / TERMGET, ≤ 3, then halt) carrying the **closing control** (`closing_control {fault, kind, status, nonce_before, nonce_after}` exactly when the control was reached — `closing.unsigned_control == done`) | `p3_app.c` `emit_summary`, `closing_unsigned_control` (keeps the fields); `p3_wire.c` summary | `termtx`: ACK; TERMGET resend identical; the bound; exhaustion halts; the real `TermHost` acks and re-acks; a STOPPED epoch's TERM carries no block; `closing_from_term` reconstructs from the C bytes |
| 6p | **every wait the timed receiver** (`p3_rectx_recv_line_timed`: idle bound = polls AND ticks, line bound = 4× each; the count-only form is the timed one with no clock); the blocking L5 `recv_line` is gone | `p3_rectx.c`, `p3_app.c` `recv_line_bounded` / `app_now_ticks` | `test_firmware_rel_audit::BoundContract`; `RelContract::test_a_torn_ack_is_partial…` |

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
`734d6c04…`, 98 324 B) and `p3_app_l6.elf` (`a2a42215…`). No compiler warning from the
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
and in the commit: 1009 tests / 1 skip / rc 0. New: `tests/test_firmware_rel_contract.py`
(17), `tests/test_firmware_rel_audit.py` (12). Updated: `tests/test_firmware_audit.py`
(14 anchors), `tests/test_firmware_wire_contract.py` (the identity test).

## 6. Asked of the owner

1. The full P3 compatibility review of this package (host-only, scoped: no board).
2. On PASS: promotion of `734d6c04…` to `pinned_at_build` (rec-v3 `403f4ab5…` superseded,
   not defective, its C1 #5 evidence kept), the freeze of the v0.6 text, then the ruling
   on the stop-loss and the first rel-v4 C1 ruling pair.
