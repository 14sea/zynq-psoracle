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

## The four L0 questions — positions on record, verdicts pending

Cross-review (owner, 2026-08-29) accepted the draft's structure and asked that each
question carry an explicit position so that the **independent, non-author L0 review** rules
on a stated claim rather than on an open field. Positions below are the author's and the
owner's provisional leans; **none is a ruling**. L0 stays `drafted / not reviewed` until
the independent review returns verdicts on all four.

| # | question | author's position | owner's provisional lean | what the L0 reviewer must rule |
|---|---|---|---|---|
| 1 | Is §3's host-computed `configuration_valid` a **re-establishment** of the interlock, or the interlock **moved to the host and thereby bypassed**? | Re-establishment: every link is checked by an instrument that observed the actual bytes (gate parsed them; oracle read them from DDR and from the fabric via PCAP); the PL asserts nothing it cannot witness (no match bit); the run-log validator recomputes the predicate and rejects a score without it; what is lost (fabric self-check) is stated. | The argument is complete but it is an **architecture judgement that a document cannot self-certify.** | ACCEPT / REJECT, with the reason. A REJECT is L0 KILL (`p3_architecture.md` §6). |
| 2 | Does the L2 heartbeat envelope need both a lower and an upper bound? | Both, pinned in `carrier_manifest.axi.heartbeat` (`advances_per_s_min/max`): a lower bound alone proves motion, not that the design is in its normal regime. | **Keep both** — a lower bound only would pass a runaway counter. | Confirm both bounds are required and that they are pinned before the L2 ruling, from a measured no-read baseline. |
| 3 | Link 2 witnessed by a **full `md.l` re-read** of the staged DDR stream, or by a hash the PS computes? | Full re-read on the host: a PS-computed hash is a match bit by another name — the host would be trusting a summary it did not observe. | **Keep the full re-read**; it is the one that matches "observed the actual bytes". | Confirm; and rule whether the re-read must cover the whole stream (`sequence_sha256` domain) or the frames only (`candidate_sha256` domain). Author: both, recorded separately, as `run_log` already distinguishes them. |
| 4 | L3's known answer: fabricmap's LUT0 candidate (49 certified bits over four frames, `known_answer.json`) or psmap's 14-bit word-51 patterns? | fabricmap's: it exercises the whitelist across four frames and the scorer's prediction, which is what L3 is for. | fabricmap's, **if the goal is to serve Claim B** — but it **cannot be pinned until L1 has re-derived the frame table and rebuilt the scorer**; pin it then, not now. | Confirm the choice and that its pinning is an L1 exit item, not an L0 one. |

**L0 exit gate, restated so it is not mistaken for a present defect:** `contracts.md` says
every schema has a validator and a conformance fixture. None exists yet; they are what L0
delivers between this draft and the independent review's PASS, together with the import
manifest for the first imported artifacts. Until they exist, L0 cannot PASS by definition.
