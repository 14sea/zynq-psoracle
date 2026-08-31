# L3 — one gated candidate end-to-end: host tooling design record

> **Status note (2026-08-31):** statements about rung status in this document are historical — what was true when it was written. The canonical status is `docs/status.md`.


Status *(historical, 2026-08-29)*: host-only, under the owner's continuous mandate. **No ruling existed;
the board was not touched.** (L3 later ran five sessions and PASSED — `docs/status.md`, `docs/l3_findings.md`.) Ruling text: `whole-of-probe P3-L3`. 198 tests.

## 1. The chain (`host/l3_runner.py`)

| step | code | authority / what is checked |
|---|---|---|
| link 1 host gate | `host/p3_gate.py` | fabricmap's `target_frame_findings` / `flush_frame_findings` **verbatim** over the three PCAP envelope streams the runner will send (parsed, never trusted); findings by `kind`; `candidate_sha256` = `run_log.frames_hash` over all 12 target frames; `sequence_sha256` over the stream words |
| session | psmap `BoardSession` | identity 17A6/verify/IDCODE, epoch, keyed-carrier setup load pinned to the manifest sha, plmark |
| stage | `stage_and_reread` | `mw.l` every word into `WR_BUF` (P1's path, 534 words per envelope) |
| link 2 PS oracle | same | `md.l` re-read of the whole buffer must equal the stream **before any DMA**; frames hash over the re-read = `staged_sha256`; stream hash = `staged_stream_sha256` (two domains, never coincide) |
| write | `execute_write` | P1's executor loop, same gates and step names (CTRL masked before/after, INT_STS cleared and verified, D_P_DONE wait, error bits → STOP), DMA `(WR_BUF|1, PCAP, 534, 0)` |
| link 3 PS oracle | `readback_frame` → psmap `execute_plan` | pinned two-DMA readback of **each of the 12 target frames**; `readback_sha256` must equal the gate's hash, else STOP — **no ARM** |
| provision | `SubprocessSigner.provision` → `sign_arm.py provision` → `provision_key_jtag.py` | the signer principal writes `K` into the write-once register over the DAP mem-AP (never the console); executes only with the `provisioning P3-K` ruling; the runner then reads STATUS `key_loaded` and STOPs (`KEY_NOT_LOADED`) if 0 — no ARM |
| ARM | `arm_and_score` | AXI precondition (alive, no fault, idle); nonce read from the PL; tag from the **gate signer subprocess** (`host/sign_arm.py`, the only program that opens `K`); 24 words staged; strobe; poll until settled; nonce must have stepped |
| score | same | only if `configuration_valid_hw` = 1: `HW_COMMIT` (8), `FUNCTIONAL_READOUT` (12), `SCORE0‥5`, heartbeat before/after; host prediction from `p3_oracle` |
| negative control | `negative_control` | one per session (a fault is sticky until reset). After the positive case: `unsigned` (zero tag), `replay` (the positive payload; the nonce has stepped), `other_candidate` (valid tag for the blank candidate, positive commit staged) → each must give `F_ARM_AUTH`; `wrong_table` (blank candidate correctly signed; fabric differs) → `F_ARM_TABLE`. **Pre-positive** (the positive attempt itself is the control): `unprovisioned` (no provisioning) → `F_ARM_NOKEY`; `wrong_key` (signer provisions a second key) → `F_ARM_AUTH`. A control that validates or scores is **KILL** |
| records | `validators/records.py` | candidate, gate_verdict (+epoch), oracle_record, arm_record, score_record, negative_control, run_log; rules (i)–(vi) checked before the run log is written; a rejected log turns the outcome into KILL |

Every AXI access goes through `Plane`, which refuses any offset outside the L1 map
host-side (an undecoded address is SLVERR → data abort → reset on this board, P2).

## 2. `host/p3_oracle.py` — pinned to fabricmap's board results

Expected tables: `lut_table.truth_table(candidate, map[key_i], base_init = 0)` with the six
LUT keys derived from the carrier's LOCs by the 7-series rule (CLBLL_L X2 → `SLICEL_X0`,
CLBLM_L X8/X9 → `SLICEM_X0`/`SLICEL_X1`, A/D LUT), each key's map mask checked against
`carrier_constants.json`. Score prediction walks the frozen vector order over the train
slice (or the holdout slice only). **Pin:** the known answer's tables and predicted scores
equal `known_answer.json`'s published numbers — train `[35,22,20,20,20,18]`, holdout
`[23,10,12,12,12,14]`, and the base's `[18,22,20,20,20,18]` / `[14,10,12,12,12,14]` — so
vector order, targets, LUT↔key mapping and bit order are all consistent with what
fabricmap measured on silicon.

## 3. What the fake proves, and what it does not

`tests/test_l3_runner.py` extends psmap's `FakeUBoot` (the console + devcfg model under
the real `BoardSession`) with a fabric that the write DMA updates and the readback DMA
reads, and the P3 PL modelled with a fixture `KeyHolder`. It proves the runner's
sequencing and stops: known answer PASS with the published scores and `HW_COMMIT` = gate
hash; holdout mode; link 2 tamper → STOP with **zero DMAs**; dropped write → link 3 STOP
with **zero ARMs**; wrong signer key → `F_ARM_AUTH`, no score, nonce consumed; the four
post-positive and two pre-positive negative controls refused with the expected faults;
`key_loaded` = 0 after a silent provisioning → STOP with zero ARMs; a PL that accepts an unsigned ARM →
KILL; a forged score rejected by the validator; gate refusal never reaches the board; the
AXI allowlist; the runner source constructs no `KeyHolder`.

It does **not** prove the PL (that is `sim/run_all.sh` on the RTL and, on silicon, the
ruling) nor the transport (psmap's board runs). The fake's PL scores with the same
`p3_oracle` predictor the runner uses — the score comparison in the fake is plumbing, not
an independent scorer model.

## 4. Residuals for the whole-line gate review

- **Five L3 sessions** (sticky fault): positive + `unsigned` / `replay` / `other_candidate`,
  plus the pre-positive `unprovisioned` and `wrong_key`; `wrong_table` optional sixth. Each
  needs its own `whole-of-probe P3-L3` ruling **and** (except `unprovisioned`) a
  `provisioning P3-K` ruling for the signer's JTAG write.
- **D4 option A implemented host-side**: the runner never sees or writes the key (tested:
  no console line names `0x2160‥216C`; `po.KEY` is in neither AXI map); the real principal
  boundary (separate OS user, pod ownership) is host setup the owner performs — until then
  the fakes model the JTAG path and `sign_arm.py` is the only key reader.
- **Staging cost**: 3 × 534 `mw.l` lines + 3 × 534-word `md.l` re-reads per candidate
  (~1,600 console commands); acceptable for L3/L4, not for L5.
- **Heartbeat bounds** in `carrier_manifest` are `null` until L2 measures them.
- `gate_verdict.findings` kinds are fabricmap's `KINDS` (`structure`, `addressing`,
  `target_frame`, `ecc`, `flush_frame`), not the contract sketch's names — the contract's
  list is illustrative; the validator only requires a `kind`.
