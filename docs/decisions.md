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

**Review #1 (2026-08-31) = HOLD** (`docs/d1_review_result.md`, verbatim). Four blockers —
the notary-refusal/epoch contradiction between §3c and §4.3; the 32-bit token in the §5b
framing against the 128-bit identity; the 32-bit carrier identifier in the identity page;
the watchdog/ring evidence disposition undefined — plus four secondary items
(closing-bracket conditionality, the audit as a bounded guarantee, Q1's narrow definition
to be accepted explicitly, §4.6's fault codes not to imply exclusive diagnosis). **v0.2
(same day) addresses all eight** (spec §12): the epoch-end taxonomy
`COMPLETED/STOPPED/PROTOCOL/CRASHED` is now the single vocabulary across schemas,
validator rules (viii)–(ix), `session_summary` and the watchdog; tokens and the carrier
sha are carried full-width everywhere; crash evidence is collector-side with post-mortem
reads `diagnostic`-only.

**Review #2 (2026-08-31) = ACCEPTED WITH Q7 CONDITION** (`docs/d1_review_result.md`,
verbatim): Q1 narrow definition accepted (the signer's per-candidate veto is permission
authority, not the search loop); Q2 accepted as a declared downgrade; Q3 T1 (T2 needs its
own non-perturbation evidence); Q4 session brackets; Q5 watchdog on; Q6 host-supplied seed
with the deterministic/test-mode label mandatory; **Q7 conditional — the C↔Python corpus N
must be pinned in the L5 design/manifest.** Not an L5 build, ruling, or board
authorisation. **Q7 condition discharged: `N = 256`**, pinned in
`fixtures/d1_corpus_v1.json` and `docs/l5_design.md` (entry 0 = blank candidate, entry 1 =
known answer, 2–255 deterministic per-index). **D1 status: reviewed, ACCEPTED WITH Q7
CONDITION (condition met). The contracts / L5-design host-only batch is authorised under
D5; L5 build, ruling and board contact are not.**

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

## D5 — batch authorisation working mode (owner, 2026-08-31)

Adopted at the D1 v0.2 acceptance, replacing step-by-step requests for host-side work:

1. **Host-only work — specifications, validators, tests, documentation sync — proceeds
   continuously within the defined scope**, without per-step requests; only commits, tests
   and change records are kept.
2. **Before any board stage**, one whole review package is submitted and the owner reviews
   it as a batch.
3. On a pass, the owner authorises that stage's **build, rulings and board sequences in one
   act**; individual small steps are not re-requested.
4. **Interrupt-and-report applies** the moment work would exceed the authorised scope, a
   specification contradiction is found, or a stop-loss event fires — those pause the batch,
   nothing else does.

The push policy is unchanged (commit locally; ask before push). Rulings remain per session,
whole-of-probe, consumed by any outcome.

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

## Addendum 2026-08-31 — D5 batch review PASS; D-c ruled (watchdog off for session 1)

The owner's D5 batch review passed the L5 host-only work and authorised the build stage
alone — toolchain, compile, manifest, linker-map — with board contact, rulings and any long
run still paused. That build is done (`docs/l5_findings.md`): xPack `arm-none-eabi-gcc`
14.2.1-1.1 pinned with a verified sha256, a hand-assembled cortex-a9 standalone BSP in
`firmware/bsp/`, and `p3_app.c` + `p3_derive.c` + `p3_search.c` compiling `-Wall -Wextra`
clean into a linked image. `p3_app.c` needed no change to compile and `p3_derive.c`
cross-compiled unchanged, so the 256-entry corpus evidence carries over untouched.

**D-a** resolved as recommended: xPack, pinned by version, URL and tarball sha256.
**D-b, D-e, D-f** confirmed as the author proposed. **D-d** resolved by evidence rather than
assumption: the console is **UART1 @ 0xE0001000**, from the D1 spec's T1 and every board
run's relay — the carrier carries no PS7 preset to read it from, because it inherits U-Boot's
state by design.

**D-c is the one the build changed.** Computing the accepted 30 s period showed it is not
reachable as written: the 32-bit A9 private watchdog at PERIPHCLK ≈ 333 MHz tops out at
12.88 s with the prescaler at its reset default, and `p3_app.c` programs no prescaler. The
finding was reported rather than patched. **Owner's ruling: option 2 — the watchdog is off
for the first L5 session** (no change to already-compiled, already-audited firmware; the
collector's 3 × H silence → `CRASHED` already bounds a hang; an N = 8 bounded bring-up is the
wrong place for un-boarded prescaler behaviour; watchdog-on can be validated separately
without touching the interlock claim).

Consequences on record: the identity page is written with `flags.bit1 = 0`;
`watchdog_load_value` is *not used* rather than unset; host recovery for a watchdog-off
session (collector declares `CRASHED`, runner stops without restoring, evidence sealed,
power cycle, **new rulings**) is fixed in `docs/l5_prereg.md` §4; a new audit test checks that
the firmware touches the SCU WDT only under that flag, because the load is 0 and a bare flag
flip would be an immediate reset; and, since no firmware changed, `app_image_sha256` is
pinned as final after a byte-identical rebuild.

**Preflight, not a blocker:** `CPU_CLK_CTRL` (0xF8000120) was never captured on the board, so
CPU_6x4x and PERIPHCLK are assumed at the standard 6:2:1 ratio (the ARM PLL itself *is*
board-confirmed). One `md.l` at first power-on discharges it; until then no timing conversion
derived from those figures may be stated as verified. Nothing in a watchdog-off session
depends on it.

Still the owner's, in this order: review the post-build package, then rule on the push, the
`whole-of-probe P3-L5` and `provisioning P3-K` rulings, and the first N = 8 session.

## 2026-08-31 — L5 post-build review (HOLD) and its host-only fix

The non-author review of the post-build package returned **HOLD** on one provenance
blocker; the accepted items and the fix are recorded verbatim + per-item in
`docs/l5_review_result.md`.

Blocker: `firmware/bsp/build.sh` compiles Xilinx `embeddedsw` sources in place, and none
were hashed, so `app_image_sha256` was reproducible only against this host's tree. Chosen
remedy = **pin, do not vendor** (avoids the third-party licence question; touches no
firmware). `manifests/l5_bsp_inputs.json` now pins all 65 embeddedsw files the build reads —
sources and their full header closure, from the pinned toolchain's own `gcc -M` output
(`host/gen_bsp_input_manifest.py`), re-hashed and drift-guarded by
`tests/test_bsp_inputs_manifest.py`. Post-build evidence bundled in `evidence/l5_build/`
(`build_evidence.json` + a tracked linker map, `host/gen_build_evidence.py`). prereg §7 marks
this round's additions as defensive strengthening, not a gate change. Image rebuilt
byte-identical (`7540239f…`); no firmware source changed. Host-only; **not pushed**.

Unchanged and still the owner's, in order: re-review the updated package, then rule the push,
`whole-of-probe P3-L5` + `provisioning P3-K`, and the first N = 8 session.

## 2026-08-31 — the L5 wire-protocol defect: image withdrawn, contract test added

The post-build re-review passed and authorised push + rulings + board. Checking the
authorised sequence before acting found that its last step had no executable, and that
search surfaced a defect in the image itself: the C application's framed output had never
been checked against the host validator that consumes it. Five findings (A–E) with their
evidence are in `docs/l5_wire_findings.md`; the root cause is that the "end-to-end
rehearsal" exercised the Python reference loop, so both ends of the chain were verified and
the join between them was empty.

Decided and done, host-only, under the owner's authorisation of a single fix batch:
the serialisation moved into a pure unit (`firmware/p3_wire.{c,h}`) that a host contract
test compiles and feeds to the **real** validator; `p3_app.c` now sends `IDENT`, `HB`,
`AUDIT` chunks and `CLOSE`, and emits `loop_record`s with `seq`/`verified`/nested
`evidence`; `host/l5_runner.py` exists. `verified: audited` means the raw words were served,
not that auditing was configured. The PL's `HW_COMMIT`/`READOUT` are read, never echoed.

**Image `7540239f…` is WITHDRAWN** (manifest `withdrawn_images`); the pinned image is
`b279459c…`, byte-identical across clean rebuilds, and `build.sh` now emits the `.bin`
itself. The preregistration's board procedure is unchanged — only the application's ability
to emit an adjudicable session is.

Standing unchanged and still the owner's: nothing pushed, no `P3-L5`/`P3-K` ruling, no board
contact, and no test result here is evidence that the firmware has run — it never has.

## 2026-08-31 — round 3 HOLD: the audit condition was not implementable

Review round 3 held the batch on a spec/implementation contradiction: the preregistration
required "session 1 audits every candidate", which no implementation can meet.

One correction to the finding's premise, checked against the source before acting: the
*current* candidate **is** audited — the request arrives during the notary exchange, before
staging, and is served after link 3 and before the record (`p3_app.c` serve_audit call
sites). The conclusion stood for a different reason: **candidates that end before staging
have no raw words at all**, so no timing can audit them.

Both halves of the reviewer's choice were taken. *Protocol:* a candidate that staged and
then refused itself at link 2 now serves its staged words before its record — its whole
claim is `staged != commit`, which the host otherwise had to take on trust — and the audit
carries `span`/`total_words` so a short audit (streams only) can never be read as a full
one. *Preregistration:* the condition is now `all-self-reporting` — every candidate that
staged is audited; a gate refusal staged nothing, is exempt, and is **recorded as exempt**,
corroborated instead by the notary log's own refusal under rule (vii).

It is machine-checked (`validators.records.check_audit_policy`, called by
`host/l5_runner.py`): a PASS cannot be reported if a self-reporting candidate went
unaudited. Marking a gate refusal `audited` would have been a false claim and was refused.

Image `b279459c…` withdrawn in favour of `d3828a8c…` (no defect in what it emitted; the
link-2 refusal was simply unauditable). 373 tests / 0 skipped. Not pushed, no ruling, no
board contact; the firmware has still never run.

## 2026-09-01 — round 4 accepted; the post-build package is submitted on baseline d3828a8c…

The reviewer accepted round 4 and asked for the new build baseline plus one complete
post-build evidence package before push, rulings or board contact.

Baseline verified from scratch, not incrementally: `rm -rf firmware/bsp/out` followed by
`build.sh` reproduces `d3828a8c…` byte-for-byte, and both the `.bin` and `.elf` hashes agree
with the manifest. `docs/l5_post_build_package.md` is the single entry point: the baseline
and its inputs, the post-build evidence, what is actually proven and by what, the audit
condition, six limitations stated as limitations, and the ordered sequence if it passes.

Added `tests/test_package_consistency.py` because the drift it guards against happened
twice in this batch: `status.md`'s L5 row accumulated contradictory text from three rounds,
and the preregistration and review package each kept a superseded image hash after a
rebuild. The guard was verified live — the preregistration was temporarily edited to name a
withdrawn hash and the test failed as it should — and that discrimination is now a
permanent test rather than a claim.

382 tests / 0 skipped. Nothing pushed, no ruling, no board contact; the firmware has still
never run on hardware.
