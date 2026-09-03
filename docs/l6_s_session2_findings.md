# L6 session S #2 (2026-09-03-03) — HOLD (transport + host collector rule): 79.6 s into the first rel-v4 soak the console lost ≈ 850 contiguous bytes spanning the tail of `HB 145 #12`, heartbeats #13–#15 and the head of `REC 145`; the merged line was HB-shaped and malformed (the session's one bad frame), and the collector's unchanged rule for a malformed non-transaction line — `CRASHED` — ended the epoch before the board's REC resend could be seen

**Standing: HOLD (prereg v0.6 §6 — `CRASHED: unparseable frame` before 1 h; §6 item 4's
"missing REC" and "missing TERM" findings follow from it). The board did not stop: 144
SCORED records in 78.9 s (the opening baseline + 143 candidates on the A,B,B,A schedule),
every one of the 11 sampled audits due by then pulled and verified with zero retries, both
forced controls exact. Not a Claim B data point; nothing is pinned; per the owner's
authorisation this S is archived and NOT re-run.** Evidence
`evidence/l6_17A6_2026-09-03-03-S/`; rulings `2026-09-03-03` (whole-of-probe P3-L6, session
S, master_seed 1278628687; provisioning P3-K; both bound to prereg `bfd69d10…`, image
`5deee74c…`, manifest `d39b339b…`; both consumed with outcome HOLD); boundary
`evidence/boundary/principal_boundary_2026-09-03-03.json` (R1–R5 PASS, minutes before).
First soak under rel-v4 and prereg v0.6; S failure #2 under §7 (S #1: v0.3/pull-v2,
`REC 465` lost ~536 bytes).

## 1. What the board did — correct until the host ended the epoch

Power cycle by the owner (UART re-enumerated 18:12, `ttyUSB4`), boundary PASS, preflight
READ (`CPU_CLK_CTRL 0x1f000200`), carrier `956379fa…`, FCLK0 50.0 MHz, IDCODE
`0x13722093`, `17A6 verify`, precheck passed, provisioning rc 0, image `5deee74c…` hash
checked. **The S plan derived by the runner from the two pinned calibration reports
(planning rates 3381.37 / 3367.75 evals/h) = the owner's numbers:** N 6061, sampled audits
382, expected inbound frames 112 575, CRC budget 451, timeout 8702 s, seed 1278628687,
abba, `rate_source: planning (D-t1)`. Identity page written (abba, N 6061, bit1/bit4/bit5),
token `6660f891…`. IDENT 1.3.0 `rel-v4` with both controls echoed, one `IDENTACK`.

`go` at 18:17:29 (IDENT t_mono 23414.48). Both controls exact on seq 1 (sign ledger
`["crc", "ok"]`, one `SIGNGET`; REC ledger `["crc", "ok"]`, one `RECGET`; the session's
only two CRC drops, `{"SIGNREQ": 1, "REC": 1}` of budget 451). 144 records, all `SCORED`,
chain length 144: seq 1 the opening baseline (`[18, 22, 20, 20, 20, 18]`), seq 2–144 the
first 143 scheduled candidates, arms alternating A,B,B,A as the schedule says (`arm_check`
not run on a CRASHED epoch; the validator accepted the 144 records: `scored 144, audited
11, chain_length 144`). The 11 sampled audits due by seq 144 (seqs 1, 2, 16, 32, …, 144)
were all pulled and verified, 0 retries, 0 timeouts, 0 waits. 16 heartbeats on every
record through seq 144. No fragment; the session's ONE bad frame is the merged line of §2 (`bad_frames 1`, recorded by the timeline); no other drop.

**Pace:** 143 inter-record evaluation intervals in 78.928 s = 0.552 s per interval —
6522.4 evaluations/hour, against the calibrations' ≈ 3370–3380: under the sampled audit policy 133 of the 144 records had
no audit stage (≈ 0.48 s of the calibration's 1.03 s period). S #1 (pull-v2) ran at the
same pace (464 records in 231 s). See §5.

## 2. The fault — one contiguous loss across five frames, ≈ 850 bytes, at go + 79.6 s

Record 145's sign exchange completed (SIGNOK 145 at t 23493.705, one attempt) and its 16
heartbeats began. Heartbeats `#0`–`#11` arrived intact (66-byte lines). Then the console
delivered ONE line of 1730 bytes:

```
P3L5 HB 145 6660f891580d1871b5050f7d20a0353f eyJpIjoxMn0= 9eRjZDIyZTk0MGI0MCIsInNjaGVtYSI6Im0X3N0cyI6IjB4NTAwM…
…xNDUsInZlcmlmaWVkIjoicmVwbGF5ZWQtb25seSJ9 51c17bd7
```

That is heartbeat `#12`'s head and payload (`{"i":12}`) with its CRC field and newline
gone, glued to the **tail** of `REC 145`: the REC line's own head (`P3L5 REC 145 <token> `,
46 bytes) and the first ≈ 590 base64 characters of its body are missing, the rest of the
body (decoded at offset 3: `…"int_sts":"0x50033004"}]}},"arm":{"ctrl_readb…` through
`…"schema_version":"1.1.0","seq":145,"verified":"replayed-only"}`) and the REC's CRC
`51c17bd7` are present. Heartbeats `#13`–`#15` never appeared: the board sends `REC`
after the sixteenth heartbeat, so the three whole heartbeat lines (3 × 67 = 201 bytes) lie
inside the lost span. Estimate of the contiguous loss: HB #12's CRC + newline (9) + HB
#13–#15 (201) + the REC head (46) + ≈ 590 body characters (REC 144's body is 2248
characters, 1663 of REC 145's remain) ≈ **850 bytes** (S #1: ≈ 536; C1 #5: ≈ 77 with the
line end; C1 #3: 308 and 228). dmesg shows no USB
event at the fault time (the `vhci_hcd urb -104` lines at 23494.23 are the port close
0.2 s after the crash).

**Why the host ended the epoch instead of recovering.** rel-v4 made every frame the board
waits for re-requestable and every board→host frame re-requestable, reconstructible or
budgeted — by *type*. The merged line reads as an `HB`-shaped frame with a malformed CRC
field: it is not REC-shaped (no `P3L5 REC 145` head), so `ConsoleSession._on_broken_line`
did not treat it as a broken REC (no `RECGET`); it is not IDENT/SIGNREQ/TERM-shaped; no
pull was open. The line therefore reached the collector, whose rule for a malformed frame
(`host/l5_notary.py` `on_line`: `FrameError → _crash("unparseable frame")`) is the one the
frame reliability design kept unchanged ("a `FrameError` … is NOT a CRC drop: it is counted
apart (`bad_frames`) and the collector's rule for it — `CRASHED` — is unchanged",
`host/l6_console.py` header). The runner then closed the port (console.log ends at that
line; timeline `BAD_FRAME` at t 23494.033, 0.2 s before the dmesg unlink) — so **the
board's own recovery was never observed**: under rel-v4 the application waits ≤ 8 s for
`RECACK 145`, resends the same REC bytes (≤ 3 transmissions) and would have been
acknowledged by a host that, having recorded the merged line as the one bad frame it
already is in the timeline, had NOT handed it to the collector. (Under v0.6 §6.11 the four
missing heartbeats #12–#15 in one record are a structural HOLD even with the REC recovered
— the rule is at most one missing per record; the budget ⌊R/1000⌋ = 6 is the aggregate —
so a v0.7 must rule that explicitly, not have it slip.)

So the failure has two parts: (a) a transport event of the known family (contiguous
console byte loss: the eighth console corruption event of the L6 line and the second that
hit a REC frame — S #1, and now S #2), and (b) a host collector rule — a malformed line that is not
transaction-shaped ends the epoch — that rel-v4 explicitly left in place and that turned
a recoverable REC transaction into a `CRASHED` end. (b) is host-side and testable with the
recorded bytes; changing it changes a frozen rule (v0.6 §6 HOLD list: `CRASHED`) and is
the owner's decision, with a re-freeze.

## 3. The crash-path findings the runner reported — two are the crash itself, one is a host reporting artefact

- `missing REC for seq [145]`, `seq 145: sign ledger without a record`, `missing TERM`,
  `no rate report: sign ledgers … do not match the records` — all consequences of the
  epoch ending between the sign exchange and the record of seq 145; correct.
- **`closing baseline scores [18, 22, 20, 20, 20, 21] != pinned`** — a host reporting
  artefact: `l6_checks.baseline_findings` takes the LAST SCORED record as the closing
  baseline; on a `CRASHED` epoch that is candidate seq 144 (a map-guided candidate whose
  scores legitimately differ), not a baseline. The finding is false as a statement about
  the board (no closing baseline was reached: `closing.baseline: not_reached`) and
  harmless to the outcome (the epoch is `CRASHED` regardless). Same class as S #1's
  crash-path defect ("0 audited where 31 were verified", fixed then). Host-only fix: check
  the closing baseline only when `epoch_end.kind == COMPLETED`.

## 4. Stop-loss classification — RULED by the owner (2026-09-03)

§7 (frozen v0.6): "a soak that fails the same way twice is the result — the next step is a
targeted fix with its own review, not a third soak." S #1 (2026-09-01-11, pull-v2) and
S #2 (2026-09-03-03, rel-v4) both ended on a contiguous console byte loss that hit a
`REC` frame within the first four minutes; the intervening C1 #6 and C2 #2 PASSed. Under
rel-v4 the REC transaction itself would have covered S #2's event; what did not cover it
is the collector's malformed-frame rule. **Owner's ruling: yes — S #1 and S #2 are "the
same way twice": the shared observable failure class is contiguous byte deletion on the
same console path running into a REC frame, losing the REC within minutes of the soak
(no claim of a proven common physical root cause). C1 #6 / C2 #2 PASSes do not reset the
soak-specific §7 rule. No third v0.6 soak; the next step is a targeted host fix, host-only
proof, independent review and a v0.7 re-freeze; no new ruling and no board before that.**

## 5. A prereg-level observation independent of the crash — the soak's N against T

Under the sampled policy the soak runs at 0.552 s per inter-record interval (only 382 of
6061 records carry an audit stage), while N was derived from the all-self-reporting
calibrations' planning rates (≈ 1.07 s per record): 6061 records at the observed pace
take ≈ 3345 s ≈ 55.8 min, so a soak that COMPLETED would still have failed v0.6 §6 item
4's "wall time ≥ 0.9 × T = 6480 s" (`host/l6_checks.soak_findings`). S #1 showed the same
pace (464 in 231 s). Neither session got far enough for the rule to fire. **Owner's
direction (2026-09-03, a design check, not a pin or a formula):** keep wall time ≥ 0.9 T
(a "2 h soak" is not to become ≈ 56 min by lowering the fraction); v0.7's preferred
route is a policy-matched planning rate computed from the two pinned calibrations'
immutable timing inputs under the soak's sampled-audit policy, then the 0.9 margin
(owner's quick check ≈ C1 6984, C2 6952 evals/h, N ≈ 12 514); S #2's 6522 evals/h may
serve only as post-hoc validation, never as an input to N; if v0.7 reuses the v0.6
calibration evidence it must import it explicitly by report hash and the three input
hashes, never as if bound to the new prereg hash — otherwise v0.7 re-calibrates.

## 6. What the owner authorised next (2026-09-03) — host-only, local commits, no push before review, no board

1. A host-only batch: a malformed `P3L5` line is recorded exactly once as `BAD_FRAME` by
   the timeline (as now), is not acknowledged, not signed, does not advance seq, and is
   NO LONGER handed to the collector to end the epoch; the replay of S #2's recorded bytes
   proves only that the host survives the line (the recording stops at the port close, so
   it cannot show the board's resend) — a modelled, byte-identical `REC 145` resend must
   follow and be accepted once with a `RECACK` and normal progress, plus the negatives:
   no resend, a wrong resend, a conflicting resend, a repeated malformed line, budget
   exhaustion; a non-fatal bad frame still needs an explicit terminal bound in S, never
   unbounded tolerance.
2. The crash-path baseline check (§3): the opening baseline always, the last record as
   the closing baseline only when `COMPLETED` (`host/l6_checks.py` `baseline_findings`).
3. v0.7 must rule explicitly on the heartbeat rule (per-record cap kept or dropped for the
   aggregate budget + index completeness + the 20 s liveness) — under v0.6 the four
   missing heartbeats of seq 145 are a structural HOLD even with the REC recovered.
4. The N-versus-T direction of §5, and then the independent review and the v0.7
   re-freeze. C1 #5 stays HOLD; `calibration.C1`/`C2` stay pinned and ACTIVE; Claim B
   stays closed.
