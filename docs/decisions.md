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

## 2026-09-01 — round 5 HOLD: a provenance manifest still named a withdrawn image

The reviewer held the package on one document-consistency blocker:
`manifests/l5_bsp_inputs.json`'s `purpose` still described the input set as feeding image
`7540239f…`, withdrawn twice over by then, so the provenance manifest and the post-build
package disagreed about the same input set.

Root cause was one level deeper than the artefact: `host/gen_bsp_input_manifest.py`
**hard-coded** that hash into the string it writes, so regenerating would have reintroduced
it. Fixed by naming the image **by reference** — `l5_manifest.json`
`pinned_at_build.app_image_sha256` — and never by value. One source of truth, no copy to go
stale.

My own guard should have caught this and did not: it scanned `docs/*.md` only. It is now
repo-wide over tracked text with an explicit allowlist of files that may keep a withdrawn
hash *because they are history*, plus a test that every allowance is still real so a stale
exemption cannot widen the hole. The guard was written and run **before** the fix and named
both the manifest and its generator; that discrimination is a permanent test.

**History was not scrubbed.** `docs/l5_findings.md`, `docs/decisions.md` and
`docs/l5_review_result.md` keep their references to the withdrawn images, as the reviewer
asked: tidying them to make a sweep pass would be falsifying the record.

The image is untouched (`d3828a8c…`, evidence regenerated and still matching); only
descriptive metadata changed. A manual repo-wide sweep corroborates the guard: every
remaining occurrence is in a historical context. 384 tests / 0 skipped. Nothing pushed, no
ruling, no board contact.

## 2026-09-01 — L5 session 1: the firmware ran, and stopped at the ARM

The post-build package passed, the owner approved the push (done: `90566b4..200065b`) and
supplied both rulings; the first L5 session ran on 17A6.

**Outcome: HOLD (STOPPED at seq 1) — the nonce did not step, so the PL never consumed the
ARM.** Classified per prereg §5. No falsification condition was met, so it is not a KILL.
Full account in `docs/l5_session1_findings.md`.

Two results worth keeping regardless of the stop. The **blocking preflight** was performed:
`CPU_CLK_CTRL = 0x1f000200` → CPU_6x4x = 666.67 MHz, exactly the assumed value, so the
manifest's PERIPHCLK figure now rests on a measurement (the 6:2:1 selection bit at SLCR
0x1C4 remains unread and is recorded as still open). And the **audit mechanism was proven
on silicon**: the eight served chunks reassemble to 2814 raw words which independently
recompute both link-2 and link-3 hashes to the signed commit. The audit is checkable, and it
checked out — the first time that has been demonstrated against real hardware data.

Three hypotheses for the ARM were tested against source and refuted (the application's own
write allowlist; a cacheable PL window — the BSP maps 0x4000_0000–0x7FFF_FFFF Strongly
Ordered; wrong offsets or strobe value — identical to the L3 sequence that armed five
times). **The root cause is not determined and is not being guessed at.**

One instrumentation gap is recorded for whoever takes the next attempt: `arm_attempt` reads
`STATUS` and `FAULT` right after the strobe and then discards them when the nonce check
fails, so the two most diagnostic values are exactly the ones not preserved.

Both rulings are consumed; a retry needs a power cycle and new ones. No firmware or spec
change has been made in response to this result.

## 2026-09-01 — the session-1 instrumentation batch (authorised; no retry)

Authorised scope after session 1's HOLD: fix the instrumentation, do not retry, do not
change the specification to explain the result. Done, and nothing beyond it.

The gap was not merely that values were discarded — the state was **unrepresentable**.
`REFUSED_BY_PL` requires the nonce to have stepped, so an ARM the PL did not consume had no
legal record and the application's only option was to stop silently. Therefore:

- `arm_attempt` now writes every observation through on all paths (`STATUS`, `FAULT`, `CTRL`
  before and after, the write count, both nonces) and no longer decides to stop: it reports,
  the caller records and then stops. `CTRL` became readable to the application; the RTL
  already exposed it read-only and L3's host read it over `md.l`.
- **`STOP_ARM` added to `LOOP_OUTCOMES` as instrumentation.** It records that an ARM was
  written and not consumed and asserts nothing about why. It demands the full ARM evidence,
  forbids a score, requires `nonce_after == nonce_before`, and **consumes no nonce in rule
  (vii)'s chain** — the PL never stepped it, so neither does the model. A `STOP_ARM` whose
  nonce *did* step is rejected, so it cannot become a catch-all for awkward results.
- The verdict is the named `outcome_for()`: only `COMPLETED` is a `PASS`, tested directly.

Three of my own tests failed correctly during this batch and were repaired rather than
bypassed: one duplicated the outcome vocabulary instead of importing it, one banned every
`p3_stop` in `arm_attempt` including the legitimate pre-ARM fault check, and one asserted
"the firmware has never run on hardware" — a premise session 1 expired. That last guard was
**retargeted, not deleted**: the canonical table's L5 state must still read HOLD.

Image `d3828a8c…` is withdrawn as **superseded, not defective**, and stays identifiable
because the session-1 evidence belongs to it. Pinned image is now `8390c463…`,
byte-identical across clean rebuilds. 392 tests / 0 skipped.

Standing: not pushed (`6a300f8` and this batch), no new ruling, board untouched since
session 1, no ARM re-issued. The root cause of the non-consumed ARM remains undetermined.

## 2026-09-01 — L5 session 2: the diagnostic run died on my own instrumentation defect

The diagnostic session specified in `docs/l5_diag_spec.md` ran and produced
`HOLD CRASHED: silence > 30s` with zero loop_records. Its own §2 says a run that fails to
produce the `STOP_ARM` evidence is an instrumentation failure, reported as one — so that is
the classification, not a hardware finding.

**Cause: a defect I introduced in the instrumentation batch.** `arm_attempt` now opens with
`axi_read(P3_CTRL)`, and `CTRL` (`0x2000`) is **write-only** — `rtl/p3_axil.v` says so in
its header, and an undecoded read is SLVERR, which on this board is a data abort. The
application died silently between the audit and the record, which is exactly the observed
console signature (IDENT, SIGNREQ, 16 HB, 8 AUDIT, then nothing).

The allowlist that would have refused the read is one I widened myself, on a false premise:
I claimed L3's host read `CTRL` over `md.l`, but that reads
`pcap_probe_plan.REG["CTRL"] = 0xF8007000` — DEVCFG's control register, a different register
in a different peripheral. Two registers sharing a name, and I did not check the RTL, which
answers it in its first ten lines.

Cost: both `-02` rulings consumed on my defect, one power cycle, one session, and nothing
learned about the non-consumed ARM. Session 1's finding stands unchanged.

**Not fixed and not re-run.** The repair is entangled with a decision that is the owner's:
`CTRL` is write-only by design, so the most direct question about session 1 — did the strobe
latch? — is unobservable from the PS without an RTL change, and a new carrier bitstream would
disturb the L1/L2/L3 evidence chain resting on `956379fa…`. Options are set out in
`docs/l5_session2_findings.md` §4 (drop the fields / add a read-only mirror / observe over
JTAG). Spending another ruling before that decision would repeat the mistake at a higher cost.

## 2026-09-01 — session-2 defect fixed: the RTL contract is not widened for an instrument

Owner's ruling on the session-2 blocker (`READ app-not-in-rtl: ['0x2000']`), applied as
given, all five items:

1. **The RTL contract is not expanded for instrumentation.** No RTL change; the carrier
   bitstream `956379fa…` is untouched, so the L1/L2/L3 evidence chain stands.
2. The `CTRL` read-back is removed from the firmware and `CTRL` is out of `axi_readable()`.
   The ARM record carries `"ctrl_readback": "unavailable: CTRL is write-only"` — the question
   is recorded as unanswerable rather than silently dropped, so a reader can tell the
   difference between "not observable" and "nobody looked".
3. The genuinely readable observations are kept: `STATUS`, `FAULT`, `writes_issued`, and both
   nonces.
4. **`tests/test_axi_map_vs_rtl.py`** is the permanent guard. Both maps are parsed from their
   own sources — the app's `axi_readable`/`axi_writable` bodies and the RTL's `ra`/`wa`
   decode — so neither side is a copy that can drift. `app − RTL` must be empty on **read and
   write**; `RTL − app` is a **closed set** — empty on read, exactly the key window
   `{0x2160, 0x2164, 0x2168, 0x216C}` on write (D4). The first version of this guard only
   asserted the key window was *contained* in the difference; the reviewer (2026-09-01) held
   the package on that gap, since one more writable offset decoded by the RTL and never named
   by the app would have passed. It now asserts equality. The parsers are themselves guarded
   with minimum-cardinality and anchor checks, because two empty sets would otherwise compare
   equal and pass vacuously. Discrimination verified live, both directions: reintroducing the
   session-2 read fails and names `0x2000`; adding `wa == 16'h2170` to the real RTL fails and
   names `0x2170`. The same mutations are also applied to an in-memory copy of the RTL inside
   the suite, so the discrimination is re-checked on every run, not only in this note.
5. Image rebuilt: **`10044abe…`**, byte-identical across two from-scratch builds. `8390c463…`
   is withdrawn as **DEFECTIVE — must not be run**; it crashes at every ARM.

**This does not explain session 1.** That ran `d3828a8c…`, built before the `CTRL` read
existed. The non-stepping nonce remains open, and no attempt is made here to account for it.

400 tests / 0 skipped. Not pushed; no new ruling; board untouched since session 2.

## 2026-09-01 — L5 session 3: HOLD (owner's ruling); the ARM stop is a premature read; design correction authorised

**Adjudication.** The runner printed `KILL run_log rejected: audit must report audited <=
total (rule ix)`. The owner ruled the session **HOLD (instrumentation defect)**: no
preregistration §3 falsifier was met; the validator's only rejection was `audit.total`
omitting the `STOP_ARM` record; the same evidence with `total = 1` validates in full; and
`KILL run_log rejected` was the runner's over-wide mapping, not a preregistration verdict.
The evidence keeps the literal string; `docs/status.md` records HOLD and the divergence.

**The observation.** `status_after = 0x901` — bit 0 = `gate_busy` — with `fault 0`,
`writes_issued 25` and the nonce unchanged: the read happened while the gate was processing
the ARM. The firmware took "not finished yet" for "not consumed". This overturns the earlier
"the gate never saw the strobe" reading. What may be written, and no more: *early-read
explanation strongly supported; standalone success after bounded settling remains untested.*

**The correction batch (host-only, authorised, done — none of it has run on hardware):**

1. `arm_attempt` polls `STATUS` after the strobe — read-only, bounded
   (`P3_SETTLE_POLLS_MAX`), the strobe written once — for L3's settle condition
   (`!gate_busy && !scorer_busy && (fault || scorer_done)`), then reads `FAULT` and the
   nonce. Three returns: consumed / settled-not-consumed (`STOP_ARM`) / not settled
   (**`STOP_SETTLE`**, new, neutral, the whole poll in the record). The closing control
   stops the epoch on a non-settling ARM without a `CLOSE` frame.
2. `TERM.audit` is `p3_wire`'s own tally of the records it serialised
   (`p3_wire_tally`), taken where the records are produced; the application keeps no
   second counter. The twin uses the same tally, so the contract test's `TERM` is counted
   by the C code under test.
3. The runner classifies a validator rejection by type: `validators.records.Falsified`
   (§3's items: (ii)/(iii), the nonce chain, a closing control not refused, a negative
   control that validated, a candidate past link 2 with `staged != commit`) → `KILL`;
   any other `RecordError` → `HOLD instrument`. `classify_rejection()` is named and
   tested both ways, including on session 3's own log.
4. Every ARM record carries `settle`; `STOP_ARM` requires `settled: true`; `STOP_SETTLE`
   requires `settled: false` and `polls == polls_max`, consumes the nonce in rule (vii)'s
   chain iff it was seen stepped, and rejects a nonce that is neither unchanged nor stepped
   once as `Falsified`.
5. Negative tests, all live-verified to fail the way they should: busy never clears
   (`STOP_SETTLE`, chain 0); busy clears and the nonce does not step (`STOP_ARM`); a
   `STOP_ARM` that never settled (rejected); a consumed ARM whose nonce did not step
   (`Falsified`); a nonce that stepped before the strobe (`Falsified` at (vii)); a `TERM`
   one short or one over (rule (ix), HOLD not KILL); a validator rejection that is not a
   falsifier classifying as HOLD; the strobe written once however long the poll; a gate
   that settles late being waited for and its stepped nonce seen — in the Python reference
   loop, which now mirrors the firmware's poll.

Image `a7c73d1f…` (byte-identical across two from-scratch builds) supersedes `10044abe…`
(withdrawn, not defective: it ran session 3). The +16 KiB is layout, not code: `.text` and
`.rodata` grew by 0x2f0 bytes, `.data`'s end crossed `0x02010000`, and the 16 KiB-aligned
`.mmu_tbl` moved up one page.

**Standing.** Prereg §6's design-review trigger stands (three sessions without
`COMPLETED`); the three-sessions stop-loss remains in force. No ruling is requested; the
board is untouched. Next: design review of this batch (`docs/l5_settle_correction.md`),
then — only if it passes — a new preregistered session.

## 2026-09-01 — design review round 1 of the correction batch: HOLD — the audit gate was a mark, not a check

The settle correction passed item by item (strobe once; read-only poll; L3's settle
condition; `STOP_SETTLE` / `STOP_ARM` separated; full poll evidence on timeout; nonce chain
distinguishes unchanged / one step / a jump; the tally on the record path; session 3's
accounting defect classifies HOLD; `a7c73d1f…` reproducible, the old image identifiable).

**Blocker.** `host/l5_runner.py` wrote `collector.audits` to `audits.json` and then called
`validate_standalone_run_log()` and `check_audit_policy()` — and the latter only checked
that self-reporting records carried `"verified": "audited"`. Nothing verified chunk
numbering, offsets or totals, reassembled the words, checked span, recomputed
`staged_sha256` / `staged_stream_sha256` / `readback_sha256`, or compared with
`evidence.app_oracle_record`. An application serving arbitrary chunks and marking its
records audited could have been reported PASS — directly against prereg §3's "audited raw
words do not recompute the compact record" — and the new `Falsified` class did not cover
that falsifier. Sessions 1 and 3 were recomputed by hand; valid evidence, not a gate.

**Fixed (host-only).** `validators/audit.py` (assembler, recompute, verify);
`validate_standalone_run_log` now takes the served chunks as a **required** argument and
the manifest, derives every record's mark from the host's own recomputation, refuses a
record whose mark disagrees, and counts rule (ix) against the host's marks; a hash that does
not recompute is `Falsified`; `check_audit_policy` takes the host's marks. The runner passes
`collector.audits` and the frame manifest and records the per-seq verification in the
summary. The contract test's session now has the C code chunk real words and the host
recompute them. Negative tests: any flipped word (stream, readback, last), chunk missing /
duplicated / gapped / overlapping / over-long / mis-spanned / wrong total / cross-seq /
bad alphabet, a record marked audited with nothing served, a streams-only audit behind a
readback claim, a false `STOP_LINK2` claim. Session 3's real chunks are the positive
fixture. `docs/l5_settle_correction.md` §3a.

Standing unchanged otherwise: not pushed, no ruling, board untouched; round-2 review next.

## 2026-09-01 — design review round 2: HOLD — one falsifier was still classed as an instrument error

The audit gate was accepted as a gate (host-derived marks, required chunk input, three
domains recomputed, hash mismatch `Falsified`, runner wiring, settle/tally/session-3
classification all standing). The blocker was inside it: after `assemble()` had accepted
the chunk stream, a staging that did not parse, a repeated envelope FAR, or an incomplete
target set raised `RecordError`, which the runner classes `HOLD instrument` — but at that
point the structural layer is clean and what fails is the *content* the application served,
which cannot support the record's hashes: prereg §3's falsifier, a KILL.

**Boundary fixed and pinned.** `assemble()` errors (chunk/schema/base64/offset/count) →
`RecordError` → HOLD. After assembly: unparseable stream / repeated envelope / incomplete
target set / hash mismatch → `Falsified` → KILL. Missing or invalid manifest → `RecordError`
→ HOLD. Negative tests both sides of the line, including through the C chunker with the
runner's own `classify_rejection` asserted (`docs/l5_settle_correction.md` §3a). Nothing
else changed; image `a7c73d1f…` untouched. Not pushed, no ruling, board untouched; round 3.

## 2026-09-01 — design review round 3: HOLD — the twelve-frame clause crossed the boundary the other way

Round 2's parse-failure and repeated-envelope branches were accepted as `Falsified`. The
third branch — "fewer than twelve target frames" — was tested by narrowing the manifest's
envelope table (mocked `p3_gate.envelopes`, three targets each → nine frames) and asserted
`Falsified`. The reviewer corrected their own round-2 requirement: under a valid manifest
that state is not constructible from served content (three parseable distinct envelopes ×
four targets = twelve, duplicates already caught), so what the test broke was the host's
interpretation, which by the pinned boundary is `RecordError` → HOLD.

**Fixed.** `recompute()` now validates the manifest-derived envelope contract *before*
interpreting any served word (`_envelope_contract`: exactly three unique far_sets, four
targets each, twelve unique target FARs equal to the pinned roles; unreadable table →
RecordError), and a frame count other than twelve after that contract is a host
implementation invariant → RecordError, not Falsified. Header destruction and repeated
envelope keep their KILL discrimination tests. Each contract clause is tested one at a time
as HOLD; a broken manifest with unparseable words yields the host-side finding first.
No firmware or image change (`a7c73d1f…`). Not pushed, no ruling, board untouched; round 4.

**Correction to the round-3 commit message (`3530bc6`).** It claimed that removing each of
the "four each" / "twelve unique" / "pinned roles" clauses was caught by the tests. The
"twelve unique" mutant in fact SURVIVED: with three envelopes of exactly four targets whose
set equals the twelve pinned roles, that clause is implied by the other two, so no
variant could reach it alone. Fixed in the follow-up commit by ordering each clause to be
the first to see its own defect and having every variant assert the clause's message — a
removed clause then changes which message appears. All four clause mutants (three unique
far_sets, twelve unique targets, four each, pinned roles) now fail the test. Recorded here
rather than by rewriting the earlier message.

## 2026-09-01 — L5 session 4: COMPLETED; adjudicated L5 PASS (scoped)

The owner checked the evidence (`evidence/l5_17A6_2026-09-01-04/`), not the runner's
string: `epoch_end COMPLETED` with all three closing steps done; ten records all `SCORED`;
opening and closing baselines `[18, 22, 20, 20, 20, 18]`; eighty audit chunks backing
10/10 audited records; validator `{scored 10, audited 10, chain_length 11}`; audit policy
over seq 1–10 with no exempt; closing unsigned control `fault 13`, `cfg_valid_hw = 0`; zero
disruptions, CRC drops and transport re-reads; every ARM from `status_first 0x901` through
sixteen reads to `status_last 0xf54` with the nonce stepping once. The early-read
explanation of sessions 1 and 3 is therefore silicon-verified on the standalone plane; all
eight §5 PASS conditions hold and no §3 falsifier is met.

**Ruling: L5 PASS (scoped).** The scope, which must be kept:

> EBAZ4203 17A6, carrier `956379fa…`, application image `a7c73d1f…`, the U-Boot→standalone control-plane crossing, a host-supplied seed, N = 8, all-self-reporting audit, under the established notary/interlock. Not extrapolated to autonomous discovery, long-run stability, other carriers/dies, Linux, or a precise ARM-gate time; `CLK_621_TRUE` unread does not affect this PASS; 16 is a count of Strongly-Ordered reads, not a time unit.

`docs/status.md` records it as the canonical state; the guard that had held the table at
HOLD is retargeted to require exactly this adjudication and its scope, so neither a wider
claim nor a drift back can appear by accident. Pushed together with the session evidence.

## 2026-09-01 — CLK_621_TRUE read (read-only ruling `-05`): 6:2:1, record closed

The one clock word the L5 line had left unread. Under a new ruling class `read-only SLCR
P3-CLK` (checked and consumed by `host/slcr_read.py` exactly as the probe rulings are), one
U-Boot session read `ARM_PLL_CTRL = 0x00028008` (fdiv 40 → 1333.33 MHz), `CPU_CLK_CTRL =
0x1f000200` (÷2 → CPU_6x4x 666.67 MHz) and **`CLK_621_TRUE = 0x00000001` → 6:2:1**, identity
verified, nothing written. PERIPHCLK = CPU_3x2x = CPU_6x4x/2 = 333.33 MHz in either mode, so
nothing in the L5 PASS depended on this bit; the manifest's clock note is now board-confirmed
rather than assumed. Evidence `evidence/preflight/slcr_17A6_2026-09-01-05.json`. The
session-1/4 findings keep their "still unread" sentences as the record of their time.

## 2026-09-01 — L6 prereg v0.2 reviewed; §4 host-only instrument batch authorised and delivered

The owner reviewed `docs/l6_soak_prereg.md` v0.2 and passed it: D-s1 (watchdog ON, the
actual prescaler/load pinned by build and tests), D-s2 (sampled audit plus firmware
auto-audit of every non-`SCORED` self-report), D-s3 (2 h, N only from the C1/C2 record
hashes and the fixed formula) and D-s4 (CRC budget from the pre-session expected frame
count; a missing AUDIT/REC/TERM an independent HOLD) are closed, and §3a resolves the
timing contradiction. `04d09ea` was pushed.

Authorised: the §4 host-only batch — frame timestamps with a raw timestamped log,
`l6_rate.py`, the sampled audit policy with its negatives, the arm-aware schema/validator
with a schedule twin, the `P3-L6` ruling grammar, calibration-hash → N/timeout, and
expected-frame-count → CRC budget. Boundary: host code, validators, fixtures, tests,
manifest draft and documents, plus a Python reference of the operators and the schedule;
**no firmware change, no two-operator image, no ruling, no board.** Delivered the same
day: `docs/l6_instrument.md` maps every item to its file and its test and lists twelve
choices the review should confirm or overturn. `manifests/l6_manifest.json` is a DRAFT
whose image, frozen-prereg and calibration pins are null, and `host/l6_runner.py` refuses
to run on it — pinned by a test. The §2 firmware/image work waits for the review.
