# L6 transport batch — delivery package for review (host-only, 2026-09-02, after C1 #5)

> **Standing: host-only, delivered, NOT reviewed. No board, no ruling, no freeze.** The
> owner's ruling of 2026-09-02 on C1 #5 (`docs/l6_c1_session5_findings.md`; decisions
> log) authorised two host-only lines: (3) a v0.5 design batch that separates the
> inclusive rate from a nominal CoV with a preregistered minimum clean sample and
> independent recovery bounds, **without re-judging C1 #5**; (4) a fix of the host-side
> defect — the reader kept an unterminated residue for ever so the resend glued to it —
> with quarantine, resync on a frame head, a monotonic deadline, a replay of C1 #5's
> bytes, discrimination tests and a host replay/fault-injection soak. Both are here.
> The §7 stop-loss the owner declared triggered (S #1 + C1 #5) stands; the owner also
> said no new board session or ruling before a complete transport/protocol review.
> Firmware, image (`403f4ab5…`), wire protocol and the frozen v0.4 text are untouched.

## 0. The owner's four rulings and where each lands

| # | ruling | landed |
|---|---|---|
| 1 | push `3e32f7a` | pushed; `origin/main = 3e32f7a` at the start of this batch |
| 2 | stop-loss TRIGGERED: S #1 + C1 #5 = two consecutive sessions lost to the same instrument/transport failure class; no board ruling until fixed and proven host-side; C2/S/Claim B paused | recorded in `docs/decisions.md`, `docs/status.md`, the manifest `status`, draft §7 |
| 3 | v0.5 host-only design batch; C1 #5 stays HOLD; `calibration.C1` null; two rates + minimum clean sample + recovery bounds; raw periods kept; C1/C2 re-run under v0.5 | `docs/l6_soak_prereg_v0.5_draft.md` (§3 D-t1..D-t3, §6 items 3, 3a–3c); `host/l6_rate.py` 1.1.0; `host/l6_checks.calibration_findings_v05`; the runner selects the rule by the manifest's prereg version; `manifests/l6_manifest.json` `next_prereg` (draft, sha null, `pass_conditions_draft`) |
| 4 | fix the reader's residue, resync on a frame head, monotonic deadline, replay C1 #5's bytes, discrimination tests, host soak; the timeout may be studied but not just re-pinned | `host/l6_reader.py`, `host/l6_audit_pull.py`, `host/l6_console.py`, `host/l6_timing.py`, `host/l6_runner.py`; `tests/test_l6_transport.py` (33); `host/l6_transport_soak.py` + `evidence/l6_transport_soak/` (5 configurations); the timeout stays 2.0 s, ≈0.5 s named as the candidate (draft D-t3) |

## 1. The defect, restated from the evidence

C1 #5, seq 39, chunk 1: the first reply reached the host as 576 bytes with no line end
(the recorded bytes: `evidence/l6_17A6_2026-09-02-01-C1/console.log`). `L6LineReader`
kept them in `buf`; the pull's timeout (2.0 s, counted by `tick(0.02)` accumulation)
expired; the resend arrived and was appended to the residue; the 1228-byte line failed
framing (`BAD_FRAME`); the third request was clean. One loss cost one timeout **and** one
wasted resend, ≈2.1 s. Every element is reproduced by test on the recorded bytes
(`C15Replay::test_the_c1_5_reader_reproduces_the_recorded_timeout_malformed_ok`).

## 2. What changed, and what proves it

| where | change | proof |
|---|---|---|
| `host/l6_reader.py` | **resync**: a `P3L5 <TYPE> <seq> <token32> ` head inside the buffer with no line end before it → the bytes before it are quarantined (verbatim, stamped, reason `resync`) and the new frame parsed from its head; **quarantine(reason)** on demand; `fragments` + `take_fragments()`; `resync=False` keeps the C1 #5 behaviour for controls | `ReaderResync` (8): torn+head → fragment 576 B + the valid resend; the same bytes without resync → one 1228-char `FrameError` line; half line across polls not torn; head split across polls not a head until complete; payload ending in `P3L5` never split (and why: the full head is required); quarantine returns the residue once; a late headless tail after the quarantine is noise, before it completes the line |
| `host/l6_audit_pull.PullHost` | **monotonic deadline** armed by every GET (`clock`, `timeout_s`), `tick()` ignores dt; **`on_timeout(seq, chunk)`** runs before the retry; **stale byte-identical reply** of a verified chunk → `ledger.duplicates`, never an attempt; a differing stale reply still a failed attempt; `Simulation` runs on a virtual clock | `PullHostDeadline` (4); every existing pull/console/wire-contract test unchanged and green (312 in the transport modules) |
| `host/l6_console.py` | takes `reader` + `clock`; on a pull timeout quarantines the residue and puts the fragment in the timeline; `tick()` absorbs the reader's resync fragments; pull ledgers carry `duplicates` | `SessionWiring` (4): timeout → `FRAGMENT` in `timeline.frames`/`fragments`, resend `ok`, `bad_frames 0`; glued duplicate → resync fragment + `ok`; ledger `duplicates`; the runner's source hands `reader=reader, clock=time.monotonic` and calls `console.tick()` |
| `host/l6_timing.Timeline` | `note_fragment`, `fragments[]` in `to_json` (schema 1.2.0), `FRAGMENT` in `NON_FRAME_EVENTS`; liveness gaps ignore it | `SessionWiring::test_liveness_gaps_ignore_fragment_events`; `test_l6_timing` unchanged |
| `host/l6_runner.py` | passes the reader and the monotonic clock; `summary["fragments"]`; hands the ledgers to the rate report; **selects the PASS rule by `prereg.version`** (v0.4 → `calibration_findings`, v0.5 → `calibration_findings_v05`) | `V05Findings::test_c1_5_is_a_hold_under_v04_and_the_runner_follows_the_manifest_not_the_draft` |
| `host/l6_rate.py` 0.2.0 / report 1.1.0 | `recovery_by_seq` (D-t2 attribution), `inclusive`, `nominal` (excluded seqs named), `recovery` indicators, per-candidate `recovery`/`clean`; top-level numbers unchanged (inclusive); CLI reads `audits.json` + `timeline.json` | `RateSplit` (5): C1 #5 → inclusive CoV 0.274 / nominal 0.056 over 62 with `[39]` excluded, recovery {1 candidate, 1 timeout, 1 malformed, 1 bad frame, 0 fragments, control 1, `rec_gets` 0}; top-level = inclusive; without ledgers nominal absent and said; the control is not a recovery but the same ledger on seq 2 is; a `FRAGMENT` in seq 10's window marks seq 10 only; `test_l6_rate` (9) unchanged |
| `host/l6_checks.calibration_findings_v05` | nominal CoV ≤ bound AND clean periods ≥ minimum AND each recovery indicator ≤ its bound; every crossing named; a missing bound refused by name | `V05Findings` (4): each of 6 bounds named when crossed, missing indicator named, report without nominal named, missing pass condition refused |
| `manifests/l6_manifest.json` | `next_prereg` (v0.5-draft, sha null, `pass_conditions_draft`, notes); `status` records the stop-loss; `prereg` stays v0.4 | `V05Findings::test_the_draft_pass_conditions_in_the_manifest_are_these`; `test_package_consistency` green |
| `host/l6_transport_soak.py` | the byte-level replay/fault-injection soak (§3) | `Soak` (3), evidence below |

## 3. The soak — what was run and what it shows

`host/l6_transport_soak.py`: for every candidate a real `PullBoard` serves real sparse
chunks built from C1 #5's recorded audit words; its lines become bytes delivered to the
reader through a channel that splits every delivery into random poll-sized reads (30 %
of the time with a boundary inside the frame head) and, with probability `p_fault` per
board→host line, applies one fault: **truncate** (tail + terminator lost — C1 #5's
shape), **interior** deletion (C1 #3 / S #1's shape), **drop**, **dup**, **glued_dup**
(a truncated copy immediately followed by a whole copy — C1 #5's merged line), or
**late_tail** (the tail arrives 0.5× or 1.5× the timeout late). Virtual time = bytes on
the wire at 115200 8N1 + the scripted delays; the host's deadline is the monotonic one
the runner uses; only `P3L5` lines reach the pull host, a headless remnant is noise.
Seed 1278624577, 2000 candidates per configuration, `evidence/l6_transport_soak/`:

| configuration | faults | single faults recovered on the FIRST resend | possible late-tail interference (recovered) | on the last permitted transmission | pulls done / failed (all failures = one chunk faulted more than the retry bound) | timeouts | stale duplicates ignored | bad frames | fragments (resync / timeout) | clean candidates with any artefact | virtual s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| resync, p 0.05, T 2.0 s | 822 | **654 / 654** | 21 (21) | 0 | 2000 / 0 | 371 | 104 | 31 | 128 / 217 | 0 | 1465 |
| resync, p 0.20, T 2.0 s | 3697 | **2245 / 2245** | 327 (327) | 43 | 1969 / 31 (31) | 1493 | 564 | 125 | 626 / 875 | 0 | 4007 |
| resync, p 0.05, T 0.5 s | 822 | **653 / 653** | 21 (21) | 0 | 2000 / 0 | 371 | 105 | 30 | 127 / 217 | 0 | 854 |
| resync, p 0.20, T 0.5 s | 3665 | **2226 / 2226** | 338 (337) | 51 | 1962 / 38 (38) | 1494 | 559 | 145 | 600 / 891 | 0 | 1516 |
| **C1 #5 reader** (no resync, no quarantine), p 0.20, T 2.0 s | 3697 | 1466 / 2132 | 255 (206) | 170 | 1753 / 247 (54) | 1507 | 543 | **1530** | 0 / 0 | 0 | 4070 |

Read: with the new reader every single fault of every kind is recovered by the first
transmission after it, at both timeouts; a pull fails only when one chunk takes more
faults than the retry bound (the D-s4/§6 rule, not this mechanism); no clean candidate
ever shows a timeout, a retry, a fragment or a bad frame. The "bad frames" that remain
are interior deletions that remove a field separator (a malformed line is a failed
attempt, recovered by the next resend) and cross-chunk merges from a late tail of another
chunk — reported apart ("possible late-tail interference"; 337 of 338 of those still
recovered on the first resend, the one exception at 0.5 s is a late remnant landing
inside the resend itself, `seq 7` in the detailed run). The C1 #5 reader on the same
seed: truncations recover on the first resend 21 times in 499, 1530 bad frames, 247
failed pulls of which only 54 are retry exhaustion — the rest are the glue defect.
At 0.5 s the invariants hold and the faulted sessions take 42 % (p 0.05) / 62 %
(p 0.20) less virtual time. **The soak measures the host mechanism over a modelled
channel; it measures nothing about the CH340/usbipd path.**

## 4. The replay of C1 #5's bytes (the owner's item 4, "prove the first resend recovers")

`tests/test_l6_transport.py::C15Replay`, on the recorded segments of seq 39 (READY,
chunk 0, the 576-byte partial, the 653-byte resend, the third copy, chunks 2–7):

| path | attempts for chunk 1 | fragments | duplicates ignored | timeouts |
|---|---|---|---|---|
| new reader + pull, the resend after the timeout | `[timeout, ok]` | 1 (576 B, `pull timeout: seq 39 chunk 1`) | 1 (the third copy) | 1 |
| new reader + pull, the resend glued in the same read | `[ok]` | 1 (`resync`) | 1 | 0 |
| new reader + pull at 0.5 s | `[timeout, ok]` | 1 | 1 | 1 |
| the C1 #5 reader (control) | `[timeout, malformed, ok]` — the recorded ledger | 0 | 0 | 1 |

## 5. What this batch does not do

- It does not change the board, the image, the wire protocol, or the frozen v0.4 text.
- It does not re-judge C1 #5: under v0.4 the runner still computes the inclusive CoV
  (test), C1 #5 is HOLD, `calibration.C1` is null. That the v0.5 draft's rule would
  raise no finding on C1 #5's evidence is stated in the draft (§6) as a fact about the
  rule, not applied.
- It does not pin the timeout: `CHUNK_TIMEOUT_S` stays 2.0 s; the draft names ≈0.5 s
  as the candidate with the C1 #5 round-trip statistics and the soak as evidence; the
  owner pins it (D-t3).
- It does not make `SIGNREQ`/`HB`/`AUDIT_READY`/`CLOSE`/`TERM` re-requestable.
- It does not lift the stop-loss or authorise any session.

## 6. Tests

`bash host/run_tests.sh` — see the report cited in the commit; `tests/test_l6_transport.py`
adds 33 (reader 8, pull deadline 4, C1 #5 replay 5, session wiring 4, rate split 5, v0.5
findings 4, soak 3). The pre-existing transport modules (reader, pull, console, timing,
runner, wire contract, rec, crash summary: 312) are unchanged and green.

## 7. Asked of the owner

1. Review of this package (host-only).
2. D-t1..D-t3 (draft §3); in particular the timeout value (2.0 s kept; ≈0.5 s candidate).
3. Freeze of v0.5 (sha into the manifest; v0.4 superseded in history) — or a HOLD with
   named items.
4. Whether the §7 stop-loss is lifted for rec-v3 + this host batch, and under what
   condition the next C1 ruling pair may be requested.
