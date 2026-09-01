# L5 session 4 on 17A6 (ruling `2026-09-01-04`) — the settle question, answered

**Standing: the runner's literal outcome is `PASS`. The canonical table keeps L5 at HOLD
until the owner adjudicates this session; this document is the evidence, not the
adjudication.** Specification: `docs/l5_session4_spec.md`. Evidence:
`evidence/l5_17A6_2026-09-01-04/`, image **`a7c73d1f…`** (first execution on hardware),
carrier `956379fa…`, boundary `evidence/boundary/principal_boundary_2026-09-01-04.json`
(R1–R5 as the runner). Power-cycled before the session; both `-04` rulings consumed.
Preflight `CPU_CLK_CTRL = 0x1f000200` (fourth identical read).

## 1. The one question — answered yes

Candidate 1 (the opening baseline, commit `3e24d936…`):

| field | value |
|---|---|
| `settle.status_first` | `0x00000901` — `gate_busy` set on the first read after the strobe, exactly as session 3 saw |
| `settle.polls` / `polls_max` / `settled` | **16** / 1 000 000 / `true` |
| `settle.status_last` = `status_after` | `0x00000f54` — `cfg_valid_hw`, `scorer_done`, `tag_ok`, `sweep_done`, `tables_match`, alive, key_loaded |
| `fault_after` | 0 |
| `writes_issued` | 25 |
| `nonce_before` → `nonce_after` | `9e3779b97f4a7c15` → `dc1b77ae0bf34dad` = `xorshift(nonce_before)` |
| outcome | `SCORED`, scores `[18, 22, 20, 20, 20, 18]` |

Per `docs/l5_session4_spec.md` §4 row 1: **the standalone application observes the stepped
nonce once it waits for the gate to settle. Sessions 1 and 3 were early reads.** The same
picture repeated on all ten ARMs of the session: `status_first` `0x901` every time, settled
after exactly 16 STATUS reads every time, the nonce stepped by the model every time. Sixteen
Strongly-Ordered reads from the A9 is the gate's whole verify-sweep-compare-score time as
seen from the PS — consistent with L3's "< 200 cycles at 50 MHz", and the first time it has
been measured from the standalone plane.

What this does not say: nothing about *why* the immediate read of sessions 1/3 saw the old
nonce beyond what the RTL already says (the nonce steps on `sh_done`); nothing about timing
in cycles (16 reads is a count, not a clock; `CLK_621_TRUE` is still unread).

## 2. The whole epoch

`COMPLETED`, reason `budget`, `last_seq 10`: opening baseline, eight search candidates
(eight distinct genomes), closing baseline, closing unsigned control. Console: `IDENT`×1,
`SIGNREQ`×10, `HB`×160, `AUDIT`×80, `REC`×10, `CLOSE`×1, `TERM`×1. Zero disruptions, zero
CRC drops, zero transport re-reads. All ten records `SCORED`, all ten `verified: audited`
**as derived by the host** (the gate of `validators/audit.py`, inside
`validate_standalone_run_log`): eighty chunks reassembled closed, and for every candidate
`staged_stream_sha256`, `staged_sha256` and `readback_sha256` recomputed from the served
words equal the record's values and the signed commit.

Independently of the validator, the same ten audits were recomputed with the second
implementation (`host/l5_refloop.py`'s functions, the recipe used for sessions 1 and 3):
all thirty hashes match. Independently of the validator, (ii) `hw_candidate_commit` and
(iii) `functional_readout` were compared with the notary's commit and tables for all ten
records, the nonce chain was re-walked from `NONCE_SEED` with a separate xorshift over the
eleven attempts including the closing control, and the closing control was checked to
carry `fault 13` (`F_ARM_AUTH`) with `cfg_valid_hw` clear: no problems.

## 3. Against `docs/l5_prereg.md` §5, item by item

| PASS requires | on the evidence |
|---|---|
| 1. `COMPLETED`, all three closing steps `done` | `epoch_end.kind COMPLETED`; `closing` = restore/baseline/unsigned_control all `done` |
| 2. opening and closing baselines score exactly `[18, 22, 20, 20, 20, 18]` | seq 1 `[18, 22, 20, 20, 20, 18]`, seq 10 `[18, 22, 20, 20, 20, 18]`; both genomes blank |
| 3. every candidate `SCORED` or `REFUSED_BY_GATE`; every `SCORED` record's `hw_candidate_commit` == notary commit and `functional_readout` == signed tables | ten `SCORED`; (ii)/(iii) hold for all ten (validator and independent check) |
| 4. the nonce chain over every attempt incl. the closing control equals the model | `chain_length 11`; re-walked independently from `9e3779b97f4a7c15`, no deviation |
| 5. the closing unsigned ARM is refused with `F_ARM_AUTH` and no score | `closing_negative`: `fault 13`, `status 0x982` (`cfg_valid_hw` clear), no `CLOSE`-side score |
| 6. every audited candidate recomputes: raw words → both link-2 hashes and the link-3 hash | 10/10 by the host gate; 10/10 by the second implementation |
| 7. `validate_standalone_run_log` accepts the log | accepted: `{scored 10, audited 10, chain_length 11}`; `check_audit_policy`: audited `[1..10]`, exempt `[]` |
| 8. zero disruptions; CRC drops within budget (16) | `disruptions []`, `crc_dropped 0` |

No §3 falsification item is met. The runner's `outcome_for` gave `PASS`.

## 4. Standing

- **The owner adjudicates.** Under §5 as written, every PASS condition holds on this
  evidence, checked by the validator and re-checked independently. The canonical table is
  changed only by the owner's ruling; until then it reads HOLD with this session recorded.
- Both `-04` rulings consumed. Board untouched since the runner exited; not power-cycled.
- Image `a7c73d1f…` produced this evidence and is unchanged.
- The three-sessions stop-loss of prereg §6 is discharged by this `COMPLETED` end; the
  design review it demanded was held (rounds 1–4).
- Open, unchanged: `CLK_621_TRUE` (SLCR `0x1C4`) still unread; the "16 reads" figure is a
  count, not a time.
