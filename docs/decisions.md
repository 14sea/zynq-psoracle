# Decisions, kill criteria, boundary — the record the owner rules on

> **Status note (2026-08-31):** statements about rung status in this document are historical — what was true when it was written. The canonical status is `docs/status.md`.


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

**Decided under the owner's continuous host-side mandate (2026-08-29): standalone.** The
L2–L4 runners stay U-Boot; L5's specification will carry the `app_identity` contract
(IDCODE + a host-written session token in the same U-Boot epoch before `go`, app-side epoch
invalidated by any reset). Recorded here as the working decision; the whole-line gate
review before the first ruling may reopen it.

**Addendum 2026-08-31 — specification drafted, not reviewed.** Under the owner's
authorisation of 2026-08-31 (D1 host-only specification only; no L5 build, no board contact,
no ruling), `docs/d1_standalone_spec.md` v0.1 makes the standalone decision concrete:
the `standalone` control plane and its crossing rules, the `app_identity` contract
(token + IDCODE + `key_loaded` + nonce echo), the per-candidate transaction with the
host as **notary** (gate + signer stay host principals — a consequence the 2026-08-29
decision did not state), `app_oracle_record` as a declared self-report distinct from
`oracle_record`, session brackets (baseline open/close + closing unsigned ARM), and the
M1-property scope table. **Seven questions (Q1–Q7) await a non-author review** (spec §10);
the D1 decision itself is unchanged. Nothing downstream (contracts 1.1, notary tooling,
L5 design, build, ruling) is authorised by the spec.

## D2 — the name and remote of this repository

Working name `zynq-psoracle` (the PS as the oracle). No remote exists; creating one is the
owner's call, as is renaming. The owner's commit/push policy applies (commit locally, ask
before push).

## D4 — key custody and provisioning (v0.3, 2026-08-29: option A adopted)

**History.** v0.2 embedded `K` as a synthesis constant; the whole-line gate review
(`docs/whole_line_gate_review_result.md`) found that the runner principal could read the
keyed bitstream (key material) and the key file (same OS user), so the "only the gate can
sign" claim was a process convention. Options in `docs/d4_principal_boundary.md`; the
owner chose **A**.

**Decision (A).** The MAC key is **provisioned at runtime** into a write-only, write-once
register by the `gate-signer` principal over JTAG (DAP mem-AP), never through the console.
The bitstream carries no key and is public. `key_loaded` (STATUS bit 11) gates every ARM
(`F_ARM_NOKEY` = 12 otherwise, sticky, nonce consumed). Custody boundary = the signer's OS
user owns `keys/` (`0400`) and the JTAG pod (udev group); the runner user has neither.
`key_id` is per session (`arm_record.signer.key_id`). Provisioning is a board action with
its own ruling text `provisioning P3-K`.

**Implemented host-only (2026-08-29):** RTL (`p3_axil.v` key register + commit,
`p3_arm_gate.v` `F_ARM_NOKEY`, `p3_siphash.v` key input), bench negatives (unprovisioned →
12, wrong key → 13, key read → SLVERR, rewrite → SLVERR, reset clears `key_loaded`),
`host/provision_key_jtag.py` (prepare/execute), `sign_arm.py` `provision` op (executes
only with the ruling), runner provisioning step + `key_loaded_observed` + pre-positive
controls `unprovisioned` / `wrong_key`, validators (rule (v) extended: no score with
`key_loaded_observed` false), public build. **Host principal setup — prepared, owner-run (re-review 2026-08-29 kept D4 on HOLD until
it exists):** `host/principal/setup_signer_principal.sh` (sudo, once: user `p3signer`
no-login, group `p3jtag`, key store `/var/lib/p3signer/keys` 0700 with `K.bin` moved and
the runner's copy shredded, `K_control.bin` for `wrong_key`, udev rule
`99-p3-signer-jtag.rules` giving the FT4232H/HS3 pods to `p3jtag`, one sudoers line
letting the runner run exactly `host/sign_arm.py` as `p3signer`), and
`host/verify_principal_boundary.py` — run **as the runner user**, it observes R1–R5
(not the signer / not in the pod group; cannot open the key; cannot open the pod node;
signer reachable via sudo and holds the key, answering `key_id` only; signer in the pod
group) and writes a `principal_boundary` record. **The L3 runner refuses to start without
a record that validates, is all-passed and < 6 h old** (`--boundary`, tested). On this
host before setup the verifier reports NOT ESTABLISHED (R2–R5), as it must.
The signer is invoked as `sudo -n -u p3signer python3 host/sign_arm.py …`;
provisioning uses `scripts/jtag_provision.cfg` (DAP + one `mem_ap` target, no Cortex-A
targets, so nothing is halted). **Setup run by the owner 2026-08-29; boundary verified as the runner with the pod attached:
R1–R5 ALL PASSED** (`evidence/boundary/principal_boundary_2026-08-29.json`; signer answers
`key_id b4c022a2…` = the moved K). First run found the signer could not traverse the 0750
home directory — fixed in the script (`chmod o+x`). Live through the real principal: a sign
request for the known answer succeeds, an unwritable verdict is refused, provisioning
`prepare` writes nothing (the script with K exists only while openocd runs), execute
without a `provisioning P3-K` ruling is a clean refusal. **Still not done:** any
provisioning on the board, any ruling.

**Stated limit — F2.** A console holder can replace the PL with a bitstream of their own
(and its own key). A does not address this; it remains excluded by the threat model
(compromised host) and is recorded in `p3_architecture.md` §3f as a limitation, not a claim.

## D3 — whether L1 (a Vivado build of the P3 carrier) is authorised

Not by this document. L1 needs: the scorer RTL imported from `zynq-fabricmap` with its
testbenches, a heartbeat counter added, ICAPE2 removed, the AXI window fixed as
`carrier_manifest` says, an OOC gate, and the frame table re-derived. It is host-side but
it is new hardware design and its own review.

**Decided under the owner's continuous host-side mandate (2026-08-29): L1 design and
build are authorised as host-side work** (RTL, simulation, Vivado synthesis/implementation,
manifest); the L1 *exit* review and everything after it remain gated; no board contact
before the whole-line gate review and a ruling. Record: `l1_design.md`.

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

**L0 review of v0.1: REJECT on Q1** (`l0_review_result.md`); Q2–Q4 ACCEPTED. **v0.2
rewrites §3 on Option A′** under the owner's six conditions (key not readable by PL/runner/
ordinary users and signer ≠ runner; provisioning, permission model and failure behaviour
defined; full-hash commitment; PL verifier, one-shot nonce and the four negative testbenches
as L1 exit gate; run-log validator as evidence consistency only; root/signer compromise
outside the threat model). **v0.2 is not reviewed.** L0 exit still requires an independent
non-author review of v0.2 plus validators, fixtures and the import manifest.


## Addendum 2026-08-29 (continuous mandate) — ruling texts and the negative-control count

- Ruling texts, psmap's model (claimed O_EXCL, consumed by any outcome): `whole-of-probe
  P3-L2` (`host/l2_runner.py`), `whole-of-probe P3-L3` (`host/l3_runner.py`). None exists.
- L3's three on-board negative controls need **three sessions** because an ARM fault is
  sticky until reset (L1, deliberate: no retry-guessing against the MAC). Each L3 ruling =
  the positive known answer + one control (`--negative unsigned|replay|other_candidate`;
  `wrong_table` optional). Alternative for the reviewer: an RTL change to a non-sticky auth
  fault — not recommended.
- Key custody as implemented (D4): `host/sign_arm.py` is the only reader of `K`; the
  runner never constructs a key holder (tested); separation is by process, same OS user —
  the residual stands.

## Addendum 2026-08-29 (whole-line gate review) — D4 is the blocker; L0 exit synced

- Verdict HOLD (`docs/whole_line_gate_review_result.md`). D4 as implemented is a process
  convention, not a principal boundary; the keyed bitstream is key material readable by the
  runner. Fix options and recommendation in `docs/d4_principal_boundary.md` (A: runtime key
  provisioned over JTAG by a separate signer user, bitstream public; B: signer-owned board
  service; C encrypted bitstream rejected — kills link 3). Owner to choose; re-review before
  any ruling.
- L0 exit: the review records it as passed; README synced. No separate verdict document.

## Addendum 2026-08-29 (later) — D4 PASS

Re-review verdict: D4 discharged (boundary verified as the runner, pod attached, R1–R5);
L1 host/build/principal preparation PASS. Defensive tightening adopted: the sudoers line
names the two fixed signer key paths instead of a trailing wildcard (setup script updated;
re-apply with sudo). No ruling exists; the board is not touched until one does.
