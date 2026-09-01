# L5 design correction after session 3 — the settle poll, the tally, the classification

**Standing: host-only, built, NOT reviewed, NOT run on hardware. No ruling requested; the
board is untouched since session 3.** This is the entry point for the design review that
`docs/l5_prereg.md` §6 requires after three sessions without a `COMPLETED` end. Owner's
authorisation and its scope: `docs/decisions.md`, entry "2026-09-01 — L5 session 3: HOLD".

## 1. What session 3 established, in the only words allowed

*Early-read explanation strongly supported; standalone success after bounded settling
remains untested.* (`docs/l5_session3_findings.md` §2; the RTL: `rtl/p3_arm_gate.v` steps
the nonce on `sh_done` in state 1, the application read it immediately after the strobe.)

## 2. The batch, item by item, and where each is proven

| ruling item | change | proof |
|---|---|---|
| bounded poll of `gate_busy` clear + the established settled condition, read-only, no re-ARM | `firmware/p3_app.c` `settle_condition()`, `arm_attempt()`: one strobe write, then `STATUS` reads until `!gate_busy && !scorer_busy && (fault \|\| scorer_done)` or `P3_SETTLE_POLLS_MAX` (1 000 000); `FAULT` and the nonce read only after | `tests/test_firmware_audit.py` `SettlePoll`: strobe count == 1, poll after the strobe, read-only inside the loop, nonce read after the poll, the condition names all four bits, `P3_ST_*` bit numbers parsed against `docs/l1_design.md` |
| timeout keeps the whole poll and is a neutral STOP | `STOP_SETTLE` in `LOOP_OUTCOMES`; the record's `arm.settle` = `{polls, polls_max, settled, status_first, status_last}`; `status_after == status_last`; no score; chain advances iff the nonce was seen stepped | `tests/test_firmware_wire_contract.py`: C-emitted `STOP_SETTLE` with nonce unchanged (chain 0) and stepped (chain 1); `settled: true` on a `STOP_SETTLE` rejected; `STOP_ARM` that never settled rejected; `tests/test_l5_refloop.py` `SettlePoll`: busy-forever ends `STOP_SETTLE` with `polls == polls_max`, validated |
| `audit.total` from the emitted loop records | `p3_wire_loop_record()` tallies every record it produces (and every audited one); `p3_wire_tally()` feeds the `TERM`; `S.audited` and `scored + refused` are gone | `test_a_counted_stop_arm_terminal_session_validates` (twin `rec` + `term` in ONE process, no explicit count → `{audited 1, total 1}`, validates); `total ± 1` rejected as rule (ix) and **not** `Falsified`; audited-flag counting |
| runner classifies rejections per prereg | `validators.records.Falsified(RecordError)` raised only for §3 items; `host/l5_runner.py` `classify_rejection()` → `KILL falsified:` / `HOLD instrument:` | `tests/test_l5_runner.py` `RejectionClassification`: both directions, the runner source no longer contains the old mapping, **and session 3's own recorded log classifies HOLD** |
| C wire twin covers a counted `STOP_ARM` terminal session | twin's `term` uses the tally unless overridden | same contract tests |
| negative tests | busy never clears; busy clears and the nonce does not step; nonce stepped early (`(vii)` → `Falsified`); consumed ARM whose nonce did not step (`Falsified`); `STOP_SETTLE` nonce jumped (`Falsified`); `TERM` one short / one over; rejection-not-KILL; strobe once however long the poll; late settle waited for | listed above; all fail the intended way when the guarded property is broken (live-verified while writing them) |

## 3. The image

| | |
|---|---|
| pinned | **`a7c73d1f010c2f78b7ad600ba406d66324970acce3b8fae515f10820cc7c230f`** (`firmware/bsp/out/p3_app.bin`, 98 324 bytes, `0x0200_0000`, `go`) |
| supersedes | `10044abe…` — withdrawn, **not defective**; ran session 3 |
| reproducibility | `rm -rf firmware/bsp/out && bash firmware/bsp/build.sh` twice: byte-identical |
| size | +16 384 bytes vs `10044abe…`: `.text` +0x1f8, `.rodata` +0xf8, `.data` end crossed `0x02010000`, the 16 KiB-aligned `.mmu_tbl` moved to `0x02014000`, objcopy pads the page — layout, not code (linker map in `evidence/l5_build/p3_app.map`) |
| toolchain / BSP inputs | unchanged, pinned as before (`manifests/l5_manifest.json`, `manifests/l5_bsp_inputs.json`) |

## 4. What this batch does not do

- It does not claim the nonce will step once the application waits. The RTL says it must
  and L3 saw it five times through the host's poll; the standalone application has never
  observed it. That is the single fact the next session exists to obtain.
- It does not touch the RTL, the carrier (`956379fa…`), the audit policy, the budget or
  the brackets. The preregistration is amended (§4 the wait, §5 the two HOLD forms, §7
  the image), not replaced: no outcome class changed, no way to pass was added.
- It does not request a ruling, and the three-sessions stop-loss remains in force.

## 5. Read in this order

1. `docs/l5_session3_findings.md` §2 — the observation and the RTL
2. `firmware/p3_app.c` — `settle_condition`, `arm_attempt`, the `armed == 2` path, `emit_summary`
3. `firmware/p3_wire.{h,c}` — `settle` in `w_arm`, the tally
4. `validators/records.py` — `Falsified`, `_check_settle`, `STOP_SETTLE`, the chain
5. `host/l5_runner.py` `classify_rejection`; `host/l5_refloop.py` `_arm`
6. the tests named in §2
7. `manifests/l5_manifest.json` `pinned_at_build`; `docs/l5_prereg.md` §4/§5/§7
