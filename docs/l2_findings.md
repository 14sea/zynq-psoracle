# L2 = P2b on 17A6 — findings

## Run #1 (ruling `2026-08-29-01`) — HOST INSTRUMENT FAULT

The operator's shell killed the runner (600 s timeout) after `L2_3_read_9`. Records: FCLK0
50.0 MHz; baseline; control OK (heartbeat 1,600,178,978 ticks in 32.03 s); **10/10 PCAP
reads PASS, state words unchanged**. No summary; board state after the kill unknown.
Fix: runners convert SIGTERM/SIGHUP into a session refusal (summary + ruling outcome always
written); board runs are launched in the background without a timeout. Evidence
`evidence/l2_17A6_2026-08-29-01/` (+ `host_note.json`).

## Run #2 (ruling `2026-08-29-02`) — HOLD (instrument): board sequence complete, adjudicator defective

Board sequence, all recorded (`evidence/l2_17A6_2026-08-29-02/`): FCLK0 50.0 → baseline →
control OK → **10/10 reads PASS** → post → **envelope write WRITTEN** (D_P_DONE in 0.20 s,
CTRL `0x4e00e07f` unchanged, INT_STS `0x50033004`, no error bits) → **readback PASS,
bit-exact** against the known answer's `0x00400A20`. Zero disruptions; two `md.l` dropped
lines re-read (§2b, counted). The adjudicator then raised `ValueError: interval 189.07 s is
outside (0, 60.0]` and the summary was written with `outcome: None`.

Post-hoc analysis of the recorded samples (analysis, **not** a verdict):

| invariant | result |
|---|---|
| state (8 words, 15 named samples) | **all equal to the baseline** (`STATUS 0x100`, rest 0) |
| heartbeat, 12 of 14 intervals (≤ 32 s) | **all inside the envelope**, 49.91–50.09 MHz |
| heartbeat, `read_9 → post` (189.07 s) and `post → write` (113.40 s) | **undecidable**: longer than the 85.9 s wrap; naive unwrapped rates would be 49.9993 / 50.0072 MHz under 2 / 1 wraps, but that is an assumption, not an observation |

Why it is an instrument defect: the spec (v1.0) required both invariants over *every*
consecutive pair while defining a post-wait equal to the reads' duration (~3 min) and a
534-word staging (~2 min) — phases longer than the counter's period. Fixed in spec v1.1
(sub-samples every ≤ 20 s across waits and staging; the fake now reproduces the long
phases and passes only with sub-samples) and the runner now records any host exception as
`CRASHED host-side` instead of leaving `outcome: None`.

Scope: nothing above is a PASS. What the two runs do show, as observations: the P3
carrier's stable-state words did not move across 10 reads + 1 envelope write + 1 readback
in either run, the write landed bit-exact, and every decidable heartbeat interval was
within 0.2 % of 50 MHz. Run #3 under spec v1.1, after the owner's review, decides L2.
