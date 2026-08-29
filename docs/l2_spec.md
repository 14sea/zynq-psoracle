# L2 = P2b — counter-class non-perturbation on the P3 carrier (specification)

Status: host-only, 2026-08-29. Runner `host/l2_runner.py`, adjudicator
`host/l2_heartbeat.py`, fake-board tests `tests/test_l2_runner.py`. **No ruling exists;
the board is not touched.** Ruling text: `whole-of-probe P3-L2`.

## 1. What L2 asks

zynq-psmap's P2 showed that PCAP reads and one PCAP write leave the carrier's eight
stable-state words unchanged. P3 needs the stronger, counter-class statement (ladder §6
L2): while the PS reads and writes configuration, a *computing* design keeps computing —
neither stalls, nor is perturbed, nor runs away. The P3 carrier exposes a free-running
32-bit HEARTBEAT (+1 per FCLK0 clock, `0x2028`) for exactly this.

## 2. Protocol — P2's, with one added observable

Identical sequence to `zynq-psmap/docs/p2_spec.md`: FCLK0 read-only decode (must be 50 ±
0.5 MHz) → baseline → no-read control (30 s, derived) → ten pinned PCAP reads of the
manifest's positive-control frame → post wait (measured, = the reads' duration) → **one
envelope write** (the known answer's envelope 0, gate-passed at link 1, staged and re-read
as in L3) → one readback of `0x00400A20` against the known answer → adjudication.

Observable per sample: P2's eight words (`STATUS, FAULT, SCORE0‥5`, same offsets) **plus
HEARTBEAT**, with the host's monotonic time taken at the heartbeat reply. The observe
allowlist is these nine `md.l` lines and the four FCLK register reads; nothing else.

## 3. Two invariants, adjudicated control-first

1. **State** (P2, unchanged): every sample equals the baseline on the eight words —
   `p2_observe.adjudicate` (imported byte-for-byte).
2. **Heartbeat** (`l2_heartbeat.adjudicate`): for every consecutive pair of samples,
   `ticks = (h₁ − h₀) mod 2³²` lies in
   `[ f·(Δt − J)·(1 − T),  f·(Δt + J)·(1 + T) ]`,
   f = decoded FCLK0, Δt = host time between the two heartbeat replies, J = 50 ms host/UART
   jitter allowance, T = 2 % — **both bounds, derived, not measured**. Δt > 60 s is refused
   (2³² / 50 MHz = 85.9 s wrap), never disambiguated.

Verdicts: control interval fails either invariant → **HOLD CONTROL_UNSTABLE** (the
observable is non-discriminating; P2's R5); a later interval fails with a stable control
→ **STOP CONTINUITY_VIOLATION** naming the step and the kind (`STALLED` / `RUNAWAY` /
`OUTSIDE_ENVELOPE`) — attributable to PCAP activity; else **PASS**, and the measured
`ticks_per_s` min/max are reported so the owner can pin `carrier_manifest.axi.heartbeat`
bounds (currently `null`) *after* L2, from evidence.

## 4. What the fake proves and what it cannot

The fake board's heartbeat is time-based on a fake clock the runner's waits advance, so
the tests exercise: PASS with both invariants; a stall after the write → attributable STOP
at `L2_6_readback`; a 2× clock → HOLD at the control, with **no write attempted**; the
observe allowlist. It cannot stand in for the transport, the real DMA, or the real PL.

## 5. Scope of a PASS

17A6, U-Boot, the P3 carrier at the manifest's sha, the nine words, ten reads + one
envelope write. Not a general "PL computes through PCAP" proof; not L3.
