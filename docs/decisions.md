# Decisions, kill criteria, boundary — the record the owner rules on

Status: draft, 2026-08-29. Each item names who decides. Nothing here is decided by this
document.

## D1 — where the evolution loop runs (deferred from `zynq-psmap/docs/line_plan.md` §6)

**Options.**

| | standalone (bare-metal app, loaded and started from U-Boot) | Linux | U-Boot scripting |
|---|---|---|---|
| devcfg access | `XDcfg` driver — the very source that settled psmap §8a | `/dev/mem` or a kernel driver; `fpgautil`'s path wedges DEVCFG on a bad load (bring-up notes) | `mw`/`md` only; no loop |
| FCLK0 | as left by U-Boot/FSBL (50 MHz on `17A6`) | `clk_disable_unused()` gates FCLK0 → the hard hang unless the dts is patched | as left |
| identity/epoch | must be **re-established by the app**: `PSS_IDCODE` from SLCR, a per-session token the host writes into a mailbox in the same U-Boot epoch before `go`, and an app-side epoch that any reset invalidates | needs a Linux-side identity gate that does not exist (`authority_requirements.md`) | psmap's, unchanged |
| deterministic timing | yes | no | n/a |
| fits the preregistration's U-Boot boundary | **the app is started from the U-Boot session and never returns to it** — a new control plane; the preregistration's "booting Linux invalidates" applies by analogy and must be ruled on, not assumed | no | yes |

**Author's recommendation:** standalone, with the identity hand-off designed as a contract
(`app_identity` schema, to be added) and reviewed before L5. It is the smallest new
authority surface and reuses the vendor driver whose reading was adjudicated.

**When it must be decided:** before L5's specification is written. L2–L4 run under U-Boot
and do not depend on D1.

**Who decides:** the owner, after cross-review.

## D2 — the name and remote of this repository

Working name `zynq-psoracle` (the PS as the oracle). No remote exists; creating one is the
owner's call, as is renaming. The owner's commit/push policy applies (commit locally, ask
before push).

## D3 — whether L1 (a Vivado build of the P3 carrier) is authorised

Not by this document. L1 needs: the scorer RTL imported from `zynq-fabricmap` with its
testbenches, a heartbeat counter added, ICAPE2 removed, the AXI window fixed as
`carrier_manifest` says, an OOC gate, and the frame table re-derived. It is host-side but
it is new hardware design and its own review.

## Kill criteria (line-wide; the per-rung ones are in the ladder)

1. A `score_record` whose interlock predicate does not recompute true in the same epoch as
   its `gate_verdict` — bypass; the line stops.
2. Any rung needs a routing-class bit, an ICAPE2 writer, or a startup transition inside a
   probe.
3. The console link's fault rate makes rulings unwinnable; fix the link and prove it with
   an authorised soak — never relax a guard.
4. A Linux dependency before D1 is decided and a Linux identity gate exists.
5. Any edit to `zynq-psmap` or `zynq-fabricmap` from this repository.

## Boundary

- This repository owns: the P3 architecture, its contracts and validators, the P3 carrier
  design (when authorised), the L2–L4 runners, and their evidence.
- `zynq-psmap` owns the PS instruments and their evidence; they are imported here by
  version, never edited here. Findings that bear on psmap go back as pointers.
- `zynq-fabricmap` owns Claim B, its preregistration and its resumption decision.
- `zynq-autoehw` owns the M1 shell and the schema policy; the heartbeat contract is
  borrowed by version.

## Open questions the reviewer should answer

1. Is §3's host-computed `configuration_valid` a re-establishment of the interlock or a
   bypass, given that the fabric no longer verifies itself? (The author's case is in §3;
   the reviewer's verdict decides L0.)
2. Does the L2 heartbeat envelope need a *lower* bound only (still computing) or also an
   upper bound (not running free)? Author: both, pinned in `carrier_manifest`.
3. Should link 2 be witnessed by re-reading the staged DDR stream in full (231+ words per
   frame set) or by a hash the PS computes? Author: full `md.l` re-read on the host — the
   PS computing a hash would be a match bit by another name.
4. Whether L3's known answer should be fabricmap's LUT0 candidate (`known_answer.json`,
   49 certified bits) or psmap's 14-bit word-51 patterns. Author: fabricmap's, because it
   exercises the whitelist across four frames and the scorer's prediction.
