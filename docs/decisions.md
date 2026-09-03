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

## 2026-09-01 — §4 batch re-review: HOLD on four semantic defects; corrected host-only

The owner's re-review of the §4 batch (`451f8b2`, not pushed): architecture right, 83
targeted tests green, but the tests had not stopped four rules from being weaker than the
preregistration — the heartbeat gap measured over frames of any type (a 40 s HB gap
filled with AUDIT/REC read as 10 s); `STOP_AXI` exempted from audit by name rather than
by "no raw self-report"; the last-candidate → closing-baseline transition inside the rate
and the CoV (and a test pinning it); and `mutation_bits = 4` called instrument-only when
the rate's `period` deliberately contains the operator's compute. Rulings: HB frames only
and an unchecked invariant is a HOLD; exemption by content, post-staging `STOP_AXI`
auto-audited (missing → HOLD, mismatch → KILL) with discrimination tests both ways;
steady-state periods only (N−1), the transitions reported apart; `mutation_bits = 4`
frozen as the image/calibration contract, a change means C1/C2 re-run. CoV over `period`,
baselines without `arm`, flags bits 2–3, the four-step pair seed (with the rule text made
exact), the timeout formula, the copied preamble, the 1.1 schema fields, `--master-seed`
and the L6 image path were accepted. All five corrections landed the same day
(`docs/l6_instrument.md` §7); push and the §2 firmware/image batch wait for the short
re-review.

## 2026-09-01 — second re-review of the §4 batch: HOLD on one blocker (HB completeness), corrected

The four corrections of `1741c53` were confirmed. Remaining blocker: the soak gate only
required two HB frames in the whole session, so a COMPLETED log with every
SIGNREQ/AUDIT/REC kept and all heartbeats after the second removed passed every gate.
Ruling: every SCORED record, the two baselines included, must carry exactly 16 HB
frames; fewer or more is a HOLD naming the seq; the check lives in the shared
structural gate so C1, C2 and S are all bound. Done as
`l6_checks.heartbeat_completeness_findings`, with the three required negatives (the
two-HB log HOLDs; one HB short on one seq names that seq; 16 each passes). Two document
syncs done with it: the delivery table's exemption wording (only `REFUSED_BY_GATE` and a
pre-staging `STOP_AXI`) and the manifest's auto-audit list (post-staging `STOP_AXI`
added). Push and §2 wait for the final short re-review.

## 2026-09-01 — §4 host-only instrument batch: PASS (third short review); §2 authorised

The owner confirmed: HB completeness counted per record seq, exactly 16 for every SCORED
record, enforced by the structural gate shared by C1/C2/S; the one-short, one-extra and
first-two-only counter-examples are each caught precisely; the STOP_AXI documents and
manifest agree with the classification-by-content implementation; the four earlier
corrections and the single-sample CoV guard hold. Independent re-run: 571 tests OK (a
pre-existing principal-boundary test skips in the review environment; the fail-closed
report here shows 571/0 skip — no contradiction).

Rulings: (1) push `451f8b2` → `1741c53` → `6ee3c38` with this adjudication commit;
(2) the §2 firmware/image batch is authorised — A/B operators, A,B,B,A / forced schedule
and pair-seed C twin; `mutation_bits = 4` and the `operator_data_sha256` contract; IDENT
1.1, the candidate arm, flags bits 2–3; sampled audit with auto-audit of every
non-SCORED self-report including a post-staging STOP_AXI; watchdog ON (prescaler 7, load
1 250 000 035, flag-gated); the 16 HB per complete SCORED record in the right seq and
order; the 256-corpus bit-exact twin; real C wire → relay → validator contract tests;
two clean byte-identical rebuilds, build evidence, manifest/image hash and the P3
compatibility review package. Boundary unchanged: no ruling, no board, no C1/C2/S in
this batch; the new image goes through the whole-package compatibility review and the
prereg freeze first, then one ruling for the board phase.

## 2026-09-01 — §2 two-operator image built and pinned (host-only); compatibility review package delivered

Under the §2 authorisation: `firmware/p3_search.c` replaced by the two operators and the
A,B,B,A / forced schedule with the pair-seed rule, the C twin bit-exact against the
256-pair corpus on arm, seed and genome; `p3_data.h` regenerated with the map tables and
their derivation hash `0c9c82a8…`; `p3_wire` emits `app_identity` 1.1.0 and `loop_record`
1.1.0; `p3_app.c` gains the schedule mode from flags bits 2–3 (mode 3 refused at
identity), the IDENT fields, the record's arm, `ensure_audit` before every non-`SCORED`
record (a post-staging pre-ARM fault now recorded as `STOP_AXI` with its words), and the
D-s1 watchdog (prescaler 7 ∥ WD mode, load 1 250 000 035, flag-gated). Two from-scratch
builds byte-identical: `47b8fa09…`, pinned in `manifests/l6_manifest.json` with
`evidence/l6_build/` and `manifests/l6_bsp_inputs.json` (the same 65 files as L5).
Found while wiring §3a: the L5 image's link-2 refusal path stopped before serving and
the serve loop required `P3_RUNNING`, so it could never have served those words — a
latent defect no session reached; fixed and pinned, not a withdrawal. The package is
`docs/l6_compat_review_package.md`. `prereg.sha256` stays null; the runner refuses;
no ruling, no board.

## 2026-09-01 — §2 compatibility review: HOLD on two blockers; corrected, image rebuilt

Blocker 1: with `flags.bit1 = 1` the IDENT frame's kick reached `XScuWdt_RestartWdt` on an
instance not yet initialised (`CfgInitialize` ran only after `establish_identity()`), so the
first L6 image `47b8fa09…` would have hung after IDENT — withdrawn as DEFECTIVE, must not
run; never ran. Fix: `S.wdt_started`, set only after `CfgInitialize` → `SetControlReg` →
`LoadWdt` → `Start` as the block's last statement; the kick tests it alone; init failure
fail-closed with a TERM; the test pins the order and catches the early-set mutant.
Blocker 2: `evidence/l6_build/build_evidence.json` cited the newest report by file name — a
green run from before the §2 sources changed — and the generator would have cited a red
one too. Fix: the report is named explicitly, read, and refused unless green; the evidence
records its sha256/count/head/result. Six package findings ruled: L5 STOP_LINK2 latent
defect accepted without withdrawing the L5 PASS; audit after a failed ARM, pre-reply
STOP_AXI → missing-REC HOLD, TERM constant 16 with the host relay as D-s4 authority, the
watchdog reset routing as a first-board observation, the RWX warning — all accepted.
Rebuilt `bd1454cd…` (byte-identical twice); report A before the evidence, report B after.
Not pushed; no freeze; no ruling; short re-review next.

## 2026-09-01 — §2 image compatibility review: PASS (host-only, scoped); push; preregistration frozen

The owner's re-review of `3c349c3`: the watchdog kick gated on `wdt_started` with the
single assignment after the full init sequence and init failure fail-closed; the build
evidence citing report A by hash, green, with report B over the final state; image
`bd1454cd…` on disk and in the manifest, `47b8fa09…` DEFECTIVE; the prereg still null so
the runner refused. Independent re-run: 627 tests, 0 failures (two environment skips).
Rulings: push `52d860a..3c349c3` (done: `origin/main = 3c349c3`); freeze the
preregistration host-only with a freeze-time guard — once `prereg.sha256` is set, the
build evidence's cited report must be non-null, present, hash-matched and green; then
present the frozen package for the board phase's overall ruling. Frozen here:
`docs/l6_soak_prereg.md` v0.2, sha256 `90f5fa699e8de8f969802b95719b3827285d65af8216e48887e026fb1fe89bcf`, pinned in
`manifests/l6_manifest.json`; `test_the_frozen_prereg_hashes_to_its_pin` and
`test_once_frozen_the_build_evidence_must_cite_a_green_report` added; the runner's own
check is unchanged and now passes on the real document (its next refusal is the image
pin, tested). No ruling exists; the board has not been touched.

## 2026-09-01 — preregistration freeze PASS; board phase HOLD on five preflight blockers; closing batch

The owner passed the freeze (prereg sha `90f5fa69…`, image `bd1454cd…`, evidence citing a
green report, C1/C2 pins null; 630 tests independently), approved the push of `31b824d`,
and HELD the board phase on five preflight blockers: (1) `--provision-ruling` optional —
the runner claimed the L6 ruling and loaded the carrier before stopping for want of a key;
(2) the P3-L6 ruling bound to nothing but its text — a C1 ruling could run C2/S; (3) the
D4 boundary record not bound to the invocation (OS user, `--signer-user`, `--key`); (4)
the carrier taken from the CLI's manifest, not the frozen one; (5) `--duration-s` free
(shrinking N and the 0.9 T floor together) and the three master seeds unpinned. Rulings:
C1 = C2 = `0x4c364341` (same seed pairs; only the operator differs), S = `0x4c36534f`,
S duration exactly 7200 s, every L6 (seed, index) tuple excluded from any future Claim B
schedule. A host-only closing batch is authorised — the fixes, session/pin binding for
both rulings, a negative test per item, and the removal of draft/null/"one ruling"
residue from `docs/l6_instrument.md` and the canonical table; no change to the frozen
prereg, the firmware or the image. Delivered in this commit: `host/l6_runner.py`
(mandatory and unconsumed P3-K ruling before any claim; `bind_ruling` for both rulings
against session / prereg / image / master seed; boundary bound to `getpass.getuser()`,
`--signer-user` and `<key_store>/K.bin`; carrier manifest and bitstream hashed against
`instrument.carrier` pins `2a7abc2b…` / `956379fa…`; seeds from the manifest, CLI seed
must match; S's T must equal the pinned 7200), `tests/test_l6_runner.py::
BoardPhasePreflight` (each blocker reached and refused by name; P3-K never consumed by a
refusal). After the closing review: a staged board batch — C1 PASS → pin C1 → C2 PASS →
pin C2 → derive N → S — with no further architecture review, and any HOLD/KILL stopping it.

## 2026-09-01 — closing review of the preflight batch: HOLD on three blockers; corrected host-only

The five preflight fixes of `2faacca` were confirmed (650 tests independently). Three more
blockers: (1) the L6 manifest — which carries the carrier pins, the soak duration and the
calibration pins — was not bound by the rulings, so a swapped manifest with prereg/image/
seed intact re-specified all three; (2) `getpass.getuser()` trusts `LOGNAME`/`USER`, so the
boundary's runner name could be forged by environment; (3) the nonce seed came from an
unbound `--l5-manifest`, so a foreign L5 manifest could turn a valid silicon nonce chain
into a false KILL. Corrections, host-only: both rulings bind `l6_manifest_sha256` (C1, C2
and S each to the manifest of their time, since the calibration pins are written between
them) with tamper tests for the carrier pin, the soak duration and the calibration pins;
the runner identity is `pwd.getpwuid(os.getuid()).pw_name`, as the boundary verifier
resolves it, with a LOGNAME/USER-forgery negative; `9e3779b97f4a7c15` is pinned in
`manifests/l6_manifest.json` `instrument.carrier.nonce_seed`, used directly, and the
`--l5-manifest` input is gone. The canonical table says closing review HOLD until the short
re-review passes. Frozen prereg, firmware and image untouched.

Test-fixture incident while correcting: the P3-K binding loop's `args()` rewrote the
fixture manifest and re-bound the rulings, so the tampered ruling passed every preflight
check and `main()` claimed the fixture ruling and tried to open the serial port — refused,
because `/dev/ebaz-uart` was absent (no board attached); no hardware was reached. The
fixture's own "no evidence dir before the checks pass" guard is what caught it. Fixed:
`args()` never rewrites the manifest, and every fixture invocation passes `--port` as a
path that cannot exist, so no test can reach a board whatever else goes wrong.

## 2026-09-01 — closing re-review PASS; push; board phase opened; C1 #1 = HOLD (transport)

The owner passed the closing re-review of `183b136` (manifest `63ab9374…`), approved the
push and opened the staged board batch for C1 only, with bound rulings `2026-09-01-06`
(session C1, master seed 1278624577, prereg `90f5fa69…`, image `bd1454cd…`, manifest
`63ab9374…`). Preflight passed every gate; boundary R1–R5 PASS. The session scored the
opening baseline and 22 candidates (16 HB and 8 audit chunks each, arm `random_safe`,
watchdog ON — the first hardware run of the two-operator image) and then lost about 38
contiguous bytes of the console stream inside seq 24's audit burst: one malformed line,
`CRASHED: unparseable frame`, validator rejection on the incomplete audit — a
transport-class HOLD (prereg §6), cause named as transport, first occurrence. The
batch is stopped; no calibration pin; C2 did not run. Second finding: the runner's
per-frame stamps are per-burst on the real transport (`drain()` returns only after 100 ms
of silence), so the stage breakdown is void while the rate (≈1470 evals/h) is sound — a
host-only instrument defect to fix before any repeat. `docs/l6_c1_session1_findings.md`
lists the options; nothing is decided here.

## 2026-09-01 — C1 #1 review: HOLD (transport) confirmed; host-only instrument batch (b) authorised, narrowed

Rulings: the transport classification stands (RecordError, not §3); `calibration.C1`
stays null; the timestamp defect is real (25 stamps for 625 frames) — rate/CoV are
reference only, the breakdown void, 1470 evals/h is not a C1 pin; two contradictions in
the authoritative state (the manifest's "never run on hardware", the canonical row's "no
C1/C2/S" beside the C1 #1 record) to be corrected with a guard; option (b) authorised in
a narrowed form: an L6-only non-blocking reader on the existing serial handle, ~20 ms
polls, stamps per read, raw bytes / partial line / banner / transport epoch preserved,
imported `board_session.py` untouched, with the listed tests; malformed `P3L5` lines are
NOT to be counted as one CRC drop (a bad line may span frames; a missing audit chunk is a
HOLD regardless) — `BAD_FRAME → CRASHED/HOLD` stays; option (c) deferred: one transport
fault does not justify firmware, audit-volume or retransmission changes. After the short
review: a new bound ruling pair and C1 #2 after a power cycle; a second byte loss of the
same kind stops board repeats (stop-loss) and moves to transport/protocol design.
Delivered here: `host/l6_reader.py`, the runner switched to it, `tests/test_l6_reader.py`,
the manifest `standing`/`hardware_history` and the canonical row corrected,
`HardwareHistoryIsConsistent` guard, `docs/l6_instrument.md` §3 corrected.

## 2026-09-01 — C1 #2 (ruling 2026-09-01-07): HOLD — the host collector's silence clock; not transport

Owner: C1 #1 record precision PASS, push approved, one power cycle and C1 #2 only, with
the stop-loss on a repeated byte loss. Power cycle, boundary PASS, preflight PASS, image
loaded, `go` — and the runner ended the epoch 0.4 s later: `CRASHED: silence > 30s`,
console 0 bytes. Cause: the `Collector` is built before the preamble, so its silence clock
was four minutes old at `go`; the blocking `drain()` had always refreshed it with the
IDENT burst before the first `poll()`, and the non-blocking reader of `1de813b` removed
that accident. Fixed host-only: silence is measured from `go`
(`collector.last_heard = collector.clock()` right after it), with a test on the real
Collector and a placement test. The same construction order in `host/l5_runner.py` is
recorded, not edited. Not a byte loss — the owner's stop-loss is not met; but the next
session is the third without COMPLETED, prereg §7's design-review trigger, for the owner.

## 2026-09-01 — C1 #2 review: HOLD (host instrumentation) confirmed; one test and the stop-loss wording corrected

The owner confirmed the cause and the fix but held `1785ff9`: the dynamic test's second
collector was built at t = 240, so its clock was already fresh and the reset it meant to
test was not needed for it to pass — a false discrimination; now both collectors are built
at t = 0 and aged 240 s, the aged one is asserted still at 0, reset to 240, then 29 s live
/ 31 s CRASHED, so removing the reset makes the test red. And the stop-loss was
overstated: two sessions currently lack COMPLETED; C1 #3 is permitted after review; if
C1 #3 is also non-COMPLETED, design review is mandatory before any fourth board session
(a repeat of C1 #1's byte loss stops repeats at once). The manifest is unchanged (sha
`20e6a924…` stands); push approved once green; no `-08` ruling until this landed.

## 2026-09-01 — C1 #3 (ruling 2026-09-01-08): HOLD (transport) — the byte loss recurred; stop-loss met

Owner-approved power cycle and C1 #3. The board completed the whole session: 66 SCORED
records (opening baseline, 64 random-safe candidates, closing baseline), both baselines
exact, the closing unsigned control refused with fault 13, TERM COMPLETED; both host
fixes held (931 distinct stamps for 1719 frames; no false silence). But two AUDIT lines
arrived with contiguous runs of bytes missing (seq 20 chunk 3: 308 bytes; seq 62 chunk 3:
228 bytes), failed CRC, were dropped, and the validator refused the log at the first
incomplete audit — a transport RecordError. This is C1 #1's fault recurring: per the
owner's standing byte-loss ruling (the basis — not §7's three-without-COMPLETED clause,
since C1 #3's device end was COMPLETED; C1 #1 and #2 were host CRASHED ends), board
repeats stop at once; no fourth C1 ruling; `calibration.C1` stays null; the line moves to
transport / protocol design, and a full design review precedes any fourth board session.
Three loss events across C1 #1 and C1 #3; C1 #2 read nothing. Found on the way: the
runner parses every inbound line before the relay and `continue`s on CrcError, so no
CRC-failed frame of any type — a broken SIGNREQ included — ever reaches
`NotaryRelay.handle_line()`; the D-s4 budget was never enforced and the summary's relay
count is always zero; the timeline is the only true counter — a host fix for the review. Informational, not pinned: 1586 evals/h, CoV 0.019, audit
1.85 s of a 2.27 s period. `docs/l6_c1_session3_findings.md` lists the options.

## 2026-09-01 — design review after the stop-loss: the host-only batch delivered

Owner's rulings: C1 #3 HOLD (transport); the byte-loss stop-loss is met on the standing
ruling (not §7); C1 stays null; `bd1454cd…` is the historical image that completed a
board epoch, not defective. Authorised and delivered host-only: (1) `host/l6_console.py`
— the timeline is the one inbound ledger and CRC authority for every frame type, the
budget is enforced there, a malformed frame is not a CRC drop, the relay never sees a
CRC failure; the C1 #3 counterfactual through the real objects counts 2 AUDIT drops
within the budget of 7 and still refuses the log for the missing chunks; negatives cover
SIGNREQ/HB/AUDIT/REC/TERM/CLOSE and the over-budget stop. (2) `host/l6_loss_stats.py` +
`docs/l6_console_loss_summary.md`: three loss events across C1 #1 and C1 #3 (39 across a
line boundary; 309 and 229 inside a line), denominators 627 complete audit lines / 719
audit frames / 2.33 MB, 96.4 % of audit words zero, no chunk-specific inference. (3)
`docs/l6_audit_pull_design.md` + `host/l6_audit_pull.py`: AUDIT_READY → AUDITGET →
AUDIT → AUDITDONE with ≤ 2 retries per chunk, every failed attempt kept and budgeted,
lossless sparse-v1 words (unlisted = zero, ascending unique positions), host rebuilds
2814 words and recomputes the three hashes; on C1 #3's real words 4 282 B vs 22 320 B,
the recorded deletions recovered by one retry, exhaustion HOLD, valid-CRC wrong content
Falsified, retransmission in the cost. Next: the owner rules on adoption, the new
firmware/image and prereg version; no board, no ruling until then.

## 2026-09-01 — pull-batch closing review: the four blockers closed; candidate image built

Per the owner's HOLD on the design batch: (1) loss denominators corrected — 626 CRC-valid
full-size lines, 630 transmission opportunities (a merged line counts as two), the JSON
caveat fixed; (2) the benefit restated as ≈ 80 % (corpus over C1 #3's 64 complete audits:
ratio 0.192–0.201, sparse 4 291–4 493 B, longest reply 676 B); (3) the transaction closed —
one seq, one span/total/chunks binding, host-side binding of token/frame seq/payload
seq/READY triple/requested chunk; (4) the model rebuilt as a real two-sided wire state
machine with lost/duplicated READY/GET/DONE, malformed-during-pull = retry, exhaustion →
AUDITABORT → STOP_AUDIT with no ARM, the board's bounded wait, sampled + §3a selection.
Beyond the blockers, the batch the owner authorised: the firmware pull in p3_app.c (the
C encoder bit-identical to Python on real words; the C pull lines drive the real host
puller), STOP_AUDIT in the validators, the console-session pull integration with the one
ledger, pull-v2 D-s4 brackets, mutation-grade static tests, two byte-identical builds →
next_image e19e1b12… pinned NOT board-ready, and the prereg v0.3 DRAFT (not frozen). The
runner still binds v0.2 + bd1454cd…; no ruling, no board. docs/l6_pull_batch_package.md
is the review's entry point.

## 2026-09-01 — whole-package review of the pull batch: HOLD on six host-integration findings; corrected

Confirmed by the owner: the 626/630 denominators, the sparse transaction binding, the
STOP_AUDIT boundaries, the firmware's no-ARM guards, the byte-identical builds, and that
v0.2/bd1454cd…/the runner bindings are untouched. Held on: (1) AUDIT_READY authority —
the session created a puller from the READY's own seq (a seq-999 READY was accepted; a
foreign-token READY was swallowed silently); now only the relay's last answered, not yet
recorded candidate may announce, anything else is PROTOCOL, and a foreign token goes to
the collector's refusal; (2) pull traffic bypassed the collector's liveness clock — a
long pull could read as silence; valid pull frames now refresh it; (3) the over-budget
CRC line was not recorded in the pull's own ledger; it is an attempt first, kept
verbatim, then the budget ends the epoch; (4) the v0.3 audit-timing definition
(READY→DONE, retries included) is implemented in l6_timing.breakdown, selected by the
frames; (5) the model double-counted the newline — one convention now, corpus
4 282–4 484 B equal to the loss summary; (6) the DONE-loss test now drives the real
validate_standalone_run_log to the rule-(ix) refusal. Package wording narrowed: dynamic
execution is the Python twins and the C serialiser twin; p3_app.c's wiring is
static/mutation coverage only. Firmware unchanged; e19e1b12… not rebuilt, still NOT
board-ready; no ruling, no board. Short re-review next.

## 2026-09-01 — pull-batch short re-review: two termination edges closed

The six integration corrections held; two edges remained. (1) An unclosed pull — READY
seen, neither DONE nor ABORT — fell back to the last chunk as the audit stage's end and
minted a full breakdown; v0.3 defines the stage as READY → DONE/ABORT, so the breakdown
is now None (the wall time stands), with the missing-both negative. (2) When retry
exhaustion and the global CRC budget fired on the same line, the epoch said
PROTOCOL_CRC_BUDGET while pulls[].why said exhaustion; the global authority now wins both
texts, the attempts and raw lines stay, and _fail() is idempotent so only one AUDITABORT
can ever be sent. Host/tests/docs only; firmware unchanged; e19e1b12… not rebuilt.

## 2026-09-01 — pull package PASS; freeze batch: prereg v0.3 frozen, e19e1b12… promoted board-ready

The owner passed the pull package (48 targeted + 770 full tests independently; A/B green;
hashes undrifted) and approved the push of the four commits (origin/main = 3495b8a), then
authorised the host-only freeze batch. Done here: the v0.3 deltas merged into
docs/l6_soak_prereg.md as a standalone frozen text (§2.6a = the pull transport with
STOP_AUDIT and the bounded wait; §3a item 1 via the pull; D-s4 = pull-v2 brackets with
retransmissions on top; §6.3 = READY→DONE audit stage, unclosed pull → no breakdown) and
its new sha pinned with the v0.2 lineage recorded; e19e1b12… promoted to pinned_at_build
with board_ready: true and protocol pull-v2 (its first hardware evidence will be a session
under a v0.3-bound ruling); bd1454cd… recorded under superseded_images — NOT defective,
the image that ran C1 #1–#3 including a complete COMPLETED epoch; next_image removed (one
image, one authority; evidence/l6_next_build/ is the candidate phase's record); the
runner refuses a pin that is not board-ready or not pull-v2 and derives the D-s4 budget
from the pull-v2 brackets (C1: 1785 expected inbound frames, budget 8); the bd1454cd…
build evidence preserved as evidence/l6_build/build_evidence_bd1454cd.json and the
directory regenerated for the promoted image citing a green report. No ruling, no board,
no C1: the frozen-artifact short review comes first, then the owner rules the ruling pair
and the power-cycle sequence.

## 2026-09-01 — frozen-artifact review: one doc-consistency blocker; the frozen text made self-contained

Code, image, runner and evidence boundaries passed; the frozen v0.3 text still carried
three v0.2 passages as if current. Corrected, documents only: Q1 now says no PASS
calibration exists to pin and accounts for the informational C1 #1/#3 rates (HOLD
sessions, superseded image, push protocol — not pinnable); the D-s2 row and §3a's blocker
paragraph are marked v0.2 HISTORICAL and state that pull-v2 resolves them (the
`serve_audit` path no longer exists); §4.1's frame/timing sequence is the pull shape,
with the push shape noted as what the C1 #1–#3 evidence contains. A guard now refuses a
frozen text that presents `serve_audit` or the nothing-measured state as current. New
prereg sha `8daa81f22add85660159e5c2474ecd4bda29d2a815c90fb5fdb8c1ef12c350ae` pinned; the manifest hash changes with it and the next ruling
pair binds the new one. Firmware and image untouched.

## 2026-09-01 — C1 #4 (ruling 2026-09-01-09): PASS — first complete, fully audited C1 under v0.3 / pull-v2; calibration pin is the owner's

Owner-issued ruling pair (whole-of-probe P3-L6 + provisioning P3-K, both binding prereg
`8daa81f2…`, image `e19e1b12…`, manifest `73ec76a7…`), power cycle, boundary PASS, then the
runner in the background with no shell timeout. The board completed the session: 66 SCORED
records (opening baseline, 64 random-safe candidates, closing baseline), both baselines
`[18, 22, 20, 20, 20, 18]`, the closing unsigned control refused with fault 13, TERM
COMPLETED/budget, 1056 HB, 528 audit chunks pulled. Every audit was served over the sparse
pull and verified (stream/staged/readback hashes equal for all 66); the inbound ledger holds
exactly the 1785 frames the prereg expects, 0 CRC drops (budget 8), 0 rereads, 0 aborts —
the byte loss of C1 #1/#3 did not occur and the retry path went unused. The validator
accepted the log; the runner wrote `rate_report.json` (`786dc3ec…`): 3909.9 evals/h, CoV
0.0159 over 63 steady-state periods, audit 0.44 s of a 0.92 s period (C1 #3: 1586 evals/h,
audit 76 % of the link). Found on the way: all 66 genomes and functional readouts are
bit-identical to C1 #3's under the superseded image — the pull firmware changed the
transport only. Recorded: `docs/l6_c1_session4_findings.md`, the manifest's
hardware_history and standing, this table. NOT done here, by the ruling's scope:
`calibration.C1` stays null until the owner pins the rate report's sha; no C2, no S, no
Claim B data, no extra diagnostics. The manifest changed (history/standing), so the C2
ruling pair binds the post-pin hash.

## 2026-09-01 — owner adjudication: C1 #4 PASS; calibration.C1 pinned; byte-loss stop-loss lifted for pull-v2

The owner re-checked C1 #4 independently and confirmed: 66 scored, 66 host-verified audits,
nonce chain 67; all 66 × 3 audit hashes recomputed equal; the 64 arms/genomes match the
random-safe schedule with brackets [1, 66]; 1785 inbound frames exactly the preregistered
count, CRC 0/8, no abort, no retry; the rate report regenerated field-identical (3909.91
eval/h, CoV 0.01588, failure rate 0); both rulings bound and consumed correctly; 774 tests
(the owner's restricted environment adds one signer-boundary skip; the in-repo report is
774 / 1 skip / exit 0). Three rulings: (1) push eb25e73 — done; (2) `calibration.C1` =
`786dc3ec9b4b30315f3656809a8907b7ee13f91d06aeeff1c52e203ecc2b5247`, pinned in
`manifests/l6_manifest.json` with the evidence path — the S runner imports rate_A only
from bytes hashing to it (D-s3); (3) the byte-loss stop-loss is lifted for pull-v2 and C2
may proceed — the historical stop-loss record is not deleted, and any future fault is
counted afresh under the frozen prereg §7. Scope note from the owner: the cross-image
genome/readout identity holds for these 66 records only and is not extrapolated to a
transport-only difference under all inputs. The manifest changed with the pin: the C2
ruling pair binds the committed post-pin hash, then power cycle, boundary, C2.

## 2026-09-01 — C2 #1 (ruling 2026-09-01-10): PASS — the map-guided calibration complete and fully audited; calibration.C2 pin is the owner's

Owner-issued ruling pair bound to the post-C1-pin manifest `d84a770a…`, power cycle (UART
re-enumerated 21:00:54), boundary PASS, runner in the background. The board completed the
session: 66 SCORED (opening baseline, 64 map-guided candidates under the shared seed,
closing baseline), baselines `[18, 22, 20, 20, 20, 18]`, closing unsigned control refused
with fault 13, TERM COMPLETED/budget. 66/66 audits pulled and verified; the inbound ledger
holds exactly the 1785 preregistered frames; 0 CRC drops of 8, 0 rereads, 0 aborts. The
validator accepted; `rate_report.json` (`a13e301f…`): 3633.0 evals/h, CoV 0.0150 over 63
steady-state periods (C1 #4: 3909.9 / 0.0159). Against C1 #4 the two baselines are
identical and all 64 candidates differ, as the operator change requires. Recorded:
`docs/l6_c2_session1_findings.md`, the manifest's hardware_history and standing, this
table. NOT done here, by the ruling's scope: `calibration.C2` stays null until the owner
pins the rate report's sha; no S, no Claim B data, no extra diagnostics. The manifest
changed (history/standing); if C2 is pinned it changes again, and the S ruling pair binds
the post-pin hash.

## 2026-09-01 — owner adjudication: C2 #1 PASS; calibration.C2 pinned; both calibrations complete; S parameters verified

The owner re-checked C2 #1 independently and confirmed: 66 scored, 66 audited, nonce chain
67; all 66 × 3 hashes equal; the 64 map-guided genomes match the twin and the schedule;
1785 inbound frames, CRC 0/8, no retry, timeout or abort; the rate report regenerated
field-identical (3632.996 eval/h, CoV 0.01501, failure rate 0); C1/C2 baselines identical
and all 64 candidates distinct; 774 tests (the review sandbox adds one signer-boundary
skip). Rulings: 5b79098 pushed; `calibration.C2` =
`a13e301f2f2ee2bbc12751fb883b4e189f0e27122e6899d5aa3c53f514568959` pinned in
`manifests/l6_manifest.json` with the evidence path — the S runner imports rate_B only
from bytes hashing to it (D-s3). The owner also verified the S parameters the two pins
derive: mode abba, seed 1278628687, N = 6539, sampled audits 412, expected inbound frames
121 449, CRC budget 486, duration 7200 s, runner timeout 8702 s — the runner derives these
itself; this record is for cross-checking, not for typing in. The S ruling pair is NOT yet
issued: it must bind the committed post-pin manifest hash, then power cycle, boundary, S.
S is not a Claim B data run; a non-PASS S is archived and reported, never re-run on the
runner's own initiative.

## 2026-09-01 — S #1 (ruling 2026-09-01-11): HOLD — a REC line lost ~536 console bytes at 231 s; archived, not re-run; a host crash-path summary defect found

Owner-issued ruling pair bound to the post-C2-pin manifest `bb63b31d…`, power cycle (UART
21:13:19), boundary PASS, runner in the background with both pinned calibration reports
and `--duration-s 7200`. The runner's derived S parameters equal the owner's independent
derivation (abba, seed 1278628687, N 6539, 412 sampled audits, 121 449 expected inbound
frames, CRC budget 486, timeout 8702 s). The board ran a correct soak for 231 s: 464 SCORED
records without gap, 7456 HB, 31/31 due sampled audits pulled and verified in one attempt,
0 rereads, 0 disruptions. Then `REC 465` arrived with one contiguous interior run of ≈536
bytes missing (1775 bytes against 2307/2315 for its neighbours), failed CRC, was dropped
(the session's only drop, budget 486), and the collector ended the epoch `CRASHED: record
seq gap: 466 after 464` — the frozen prereg §6 item 4 makes a missing REC fatal regardless
of budget, and pull-v2 has no REC re-request. The board itself continued (SIGNREQ 467
seen). dmesg shows no host USB event at the fault; the ghost ttyUSB0 FTDI disconnect maps
to 24 s before `go`. This is the C1 #1/#3 byte-loss family, first time on a REC line.
Second finding, host-side: the collector-synthesised crash-path `session_summary` carries
`audited 0` while 31 audits were host-verified, so the validator's stated reason is (ix)
rather than the seq gap — a defect to fix before the next S. Classification: HOLD
(transport; CRASHED < 1 h, the repeat-once clause does not apply); §7 count S failure #1;
per the owner's ruling the session is archived and NOT re-run. Recorded:
`docs/l6_s_session1_findings.md` (§5 options: REC re-request in the pull protocol, the
crash-path summary fix, extending the loss statistics), the manifest's hardware_history
and standing, this table. No Claim B data, no extra diagnostics. The manifest changed.
Awaiting the owner.

## 2026-09-01 — pre-board protocol correction batch after S #1 (host-only; firmware, image and prereg draft change): the REC transaction (rec-v3)

Owner-authorised after S #1's HOLD, explicitly NOT host-only in scope (firmware, image and
prereg draft) and explicitly bounded: no board, no ruling, no v0.4 freeze, no S re-run,
continuous to a complete review package. Delivered: (1) the loop record is a transaction —
`REC` → `RECACK` | `RECGET` → the SAME bytes again, at most three transmissions, the board's
wait bounded, an unacknowledged record `STOP_REC` with no next candidate; token, seq and
current-candidate authority closed (a REC for another seq or a SIGNREQ over an
outstanding record is PROTOCOL), duplicates idempotent (re-acknowledged, never appended;
other content for the same seq is PROTOCOL, never a second accepted record); (2) exhaustion
stops; (3) every attempt and the original broken line in the one inbound ledger and a
per-seq REC ledger (`audits.json` `recs[]`), content left to the validator (a valid-but-wrong
record accepted once, never retried); (4) the crash-path summary's `audited` from the host
audit gate's marks (`host/l6_checks.crash_audit_count`); (5) the S #1 counterfactual as a
test: with 31 the validator accepts the 464 records and the structural gate names the
missing REC/TERM — HOLD, never PASS; (6) loss statistics over all six sessions and every
frame type (four events, exposure only); (7) the preregistered forced REC-retry control
(identity page flags.bit4: seq 1's first transmission CRC-corrupted on purpose, the retry
proven within seconds, `rec_control_findings` a HOLD if not exercised), armed by the
runner in every session; (8) prereg v0.4 DRAFT (`docs/l6_soak_prereg_v0.4_draft.md`; v0.3
frozen and untouched, `prereg.protocol: pull-v2` recorded in the manifest); (9) the rec-v3
image built twice byte-identical — `cd8360dc…` as `next_image`, `board_ready: false`,
never run. The owner's condition on calibrations: every rate report now carries a
`binding` (image, prereg, protocol, session, mode, seed) written by the runner, and the S
runner refuses a calibration without one or with another binding — the v0.3 C1/C2 pins
stay recorded and are refused by construction; C1 and C2 are re-run under the rec-v3 image
before any S. The runner refuses to run against v0.3 or a pull-v2 image at all
(`HOST_PROTOCOL = rec-v3`). Evidence of the C state machine is dynamic: `firmware/p3_rectx.c`
(pure, the same source the image links) runs on the host over a pipe against the real
frame parser and the real host side (`RecWireContract`); the `p3_app.c` wiring is static.
Package: `docs/l6_rec_batch_package.md`; design: `docs/l6_rec_transaction_design.md`.
Suite 855 tests / 1 skip. Awaiting the owner's full P3 compatibility review.

## 2026-09-02 — owner's review of the rec-v3 batch: HOLD on four blockers; correction batch (host + firmware), first candidate withdrawn DEFECTIVE

The owner held the batch: (1) the "bounded receive" bounded only the first byte of a host
line and then blocked for the newline — a RECACK/RECGET cut mid-line would have held the
application until the watchdog, not resent and not STOP_REC; (2) a CRC-broken resend of an
accepted record was re-acknowledged on its readable header, which cannot prove the
byte-identical duplicate v0.4 requires, and the RecHost twin did otherwise; (3) v0.4 PASS
condition 7 (every record closed by a host RECACK) was not machine-enforced — only seq 1
was checked; (4) the control check accepted a prefix and ≥ 1 GET, the sign-reply wait
skipped any token-valid acknowledgement without checking the seqs, and the stale limit
tolerated a 65th line. Confirmed correct: v0.3 and e19e1b12… untouched, the runner refuses
the committed v0.3/pull-v2 pair, the old calibrations refused, the S #1 counterfactual,
the loss statistics, the C transaction under whole-line input. Authorised: a host+firmware
correction batch, cd8360dc… marked DEFECTIVE, a new candidate rebuilt twice, then a short
re-review; no push, no freeze, no ruling, no board.

Closed: `p3_rectx_recv_line` — the whole-line receiver in the pure unit (idle bound
between bytes, overall line bound 4 × idle, -3 partial), `p3_app.c` supplying only the RX
primitives; the wire twin feeds every host line byte by byte through it, and the contract
test proves a truncated ACK, a GET without its newline and a four-byte fragment are
abandoned and the record resent, and three truncated ACKs exhaust to STOP_REC. A broken
resend of an accepted record now draws RECGET and only an equal CRC-valid resend earns the
RECACK (other content → PROTOCOL_REC; the twin and the session agree). `rec_closure_findings`
enforces PASS condition 7 over the whole session (record seqs == ledger seqs, accepted, no
conflict, ≥ 1 RECACK, an accepted attempt, no extra or missing ledgers), the runner calls
it, and the discrimination test removes an arbitrary middle ledger. The control check
requires exactly ["crc", "ok"], accepted, one RECGET, an ACK (the draft says so); the
sign-reply wait skips an acknowledgement only when frame seq and payload seq both name
the previous transaction, else PROTOCOL; the 64th ignored line ends the wait. cd8360dc…
is withdrawn DEFECTIVE (build record preserved); 403f4ab5… (ELF 8687ef8d…) built twice
byte-identical is next_image, not board-ready. Draft v0.4 §2.6c/6e/6f, D-r3 and PASS
condition 7 updated. 863 tests, 1 skip. Not pushed; awaiting the owner's short re-review.

## 2026-09-02 — owner's targeted re-review of the rec-v3 correction batch: PASS; push, promotion and freeze deferred to the full review

The owner re-reviewed the four blockers and found each substantively closed and no new
blocker: (1) `p3_rectx_recv_line` bounds both inter-byte silence and the whole line, a
truncated line returns -3 and the transaction counts it stale, and the tests drive the
same C receiver, not a Python stand-in; (2) a CRC-broken duplicate now draws RECGET and
only a CRC-valid, payload-equal resend is acknowledged, other content PROTOCOL_REC, the
old pinning test reversed; (3) `rec_closure_findings` closes the record/ledger sets,
accepted, conflict, ACK and accepted attempt, is called by the runner, and the
"seq 1 only" counter-example names [2, 3, 4]; (4) the control requires exactly
["crc", "ok"], one GET, an ACK, no conflict; the sign-reply wait checks the previous
transaction's frame and payload seq; the 64th stale line ends the wait. Artifact
boundary confirmed: v0.3 `8daa81f2…` unchanged; board-ready `e19e1b12…` unchanged;
`cd8360dc…` DEFECTIVE with its build record kept; `403f4ab5…` hashes as the manifest and
build evidence say and stays `board_ready: false`; v0.4 a draft with a null hash; the
committed manifest cannot start a rec-v3 session. Independent re-run 863 OK (the review
environment's extra skip is its signer-boundary limit; the committed report is 1 skip).
Ruled this round: the correction batch PASSES. NOT yet approved: push of 6fe2d51 +
eab69c5, image promotion, v0.4 freeze. Next: the owner's full P3 compatibility review of
`docs/l6_rec_batch_package.md`; on its pass, push, promotion and freeze are ruled again.
Board and rulings stay forbidden.

## 2026-09-02 — full P3 compatibility review of the rec-v3 batch: PASS (host-only, scoped); push approved; promotion/freeze batch executed

The owner's full review found no remaining blocker and ruled PASS — host-only, scoped: not
a board or L6 session PASS. Checked: the P3 core interlock unrelaxed (RTL, carrier, AXI
decode, DMA, oracle, ARM, score untouched; REC closes delivery and adds no scoring path);
the REC transaction closed and bounded (one serialisation, same bytes ≤ 3, inter-byte and
whole-line bounds, STOP_REC on exhaustion; the candidate ELF's linker map links the same
firmware/p3_rectx.c the host test drives); the host acceptance boundary (first valid REC
once; identical resend re-ACKed; other content PROTOCOL_REC; broken REC re-requested,
never ACKed on a header; foreign seq / advance-without-ACK terminate); PASS not narrative
(record/ledger seq sets equal, accepted, no conflict, attempt, RECACK; the control's exact
shape); audit/CRC/KILL-HOLD boundaries kept; calibrations not reusable across protocols
(binding; the pull-v2 reports refused); image and provenance (403f4ab5… twice from
scratch; cd8360dc… DEFECTIVE; e19e1b12… the pull-v2 authority at the time; S #1
counterfactual still a HOLD). 863 tests independently. Rulings: push 6fe2d51, eab69c5,
2b2096f — done; a single host-only promotion/freeze batch — done in this commit:
403f4ab5… is the sole pinned_at_build (board_ready true, protocol rec-v3); e19e1b12…
moved to superseded_images, NOT defective, its hardware_history (C1 #4, C2 #1, S #1)
attributed and kept; cd8360dc… stays DEFECTIVE; the v0.4 draft merged into the
self-contained frozen docs/l6_soak_prereg.md (new sha pinned in the manifest; v0.3 and
v0.2 in the supersedes chain and in git history; the draft file marked merged/historical);
calibration.C1/C2 null under rec-v3, the pull-v2 pins kept as calibration.historical_pull_v2
with the tests proving they cannot be fed to S; the manifest's status, the authority
guards (tests/test_package_consistency.py: protocol rec-v3, two superseded, two withdrawn,
v0.4 present tense, historical calibrations) and evidence/l6_build regenerated for the
promoted image (the e19e1b12… record preserved). Not ruled: any ruling or board
operation. Next: a frozen-artifact/hash short review of this batch; on its pass, the
rec-v3 C1 and C2 ruling pairs are issued separately.

## 2026-09-02 — frozen-artifact/hash short review of the promotion/freeze batch: PASS; cb072eb pushed; rec-v3 C1 eligible for its ruling pair

The owner confirmed the four artefact hashes (prereg 12799ef9…, manifest f12b6958…, image
403f4ab5…, ELF 8687ef8d…), 403f4ab5… as the sole board-ready rec-v3 authority with
next_image/next_prereg removed, e19e1b12… superseded and not defective with the six
sessions' evidence attributed without drift, cd8360dc… DEFECTIVE, calibration.C1/C2 null
with the pull-v2 pins only in historical_pull_v2 and refused across protocols, the frozen
v0.4 text self-contained, and — with the real manifest, prereg and image and a correctly
bound but unclaimed ruling/boundary in /tmp — the runner's preflight producing a C1 /
rec-v3 / N = 64 / control-armed plan. 864 tests green independently. One non-blocking
cleanup: a redundant assertion message in tests/test_l6_runner.py claimed "the committed
manifest cannot run" where the case only triggers the image-pin refusal with a stand-in —
reworded in this commit to what it tests. Rulings: push cb072eb (done); promotion/freeze
formally passed; not a C1 or L6 board PASS; no ruling issued yet. After the push the
rec-v3 C1 is eligible to request its own ruling pair and power-cycle sequence.


## 2026-09-02 — rec-v3 C1 #5 on 17A6 under ruling pair `2026-09-02-01`: HOLD (instrument, §6 item 3 — CoV 0.274 after one recovered audit byte loss); archived, not re-run

The owner issued the P3-L6 (session C1, master_seed 1278624577) and P3-K rulings bound to
prereg `12799ef9…`, image `403f4ab5…`, manifest `f12b6958…`, and authorised one power
cycle and one C1 epoch, any non-PASS to be archived without a re-run; the authorisation
did not cover C2, S or Claim B. Executed in order: rulings written verbatim; UART
re-enumeration confirmed (18:04:26); boundary as the runner principal PASS (R1–R5,
`principal_boundary_2026-09-02-01.json`); runner in the background without a shell
timeout, waited on by pid. Outcome: the epoch COMPLETED with every §6 condition but item 3
met — 66/66 audited, the forced REC-retry control exactly `[crc, ok]`, REC closure clean,
1785 frames exact, one CRC drop (the control) of budget 8 — and one console byte loss
inside `AUDIT 39` chunk 1, which the pull recovered (timeout → merged resend rejected as
`BAD_FRAME` → clean third reply) at a cost of ≈2.1 s in one period, giving CoV 0.274
(0.056 without that period, informational only). Both rulings consumed with outcome HOLD.
Nothing pinned; `calibration.C1` stays null. Archived: `docs/l6_c1_session5_findings.md`,
`hardware_history` (66/1/64/1), the manifest standing (the image has now RAN ON 17A6),
this note; loss statistics regenerated over seven sessions. Open for the owner (findings
§5): the §7 count (S #1 + C1 #5 as consecutive byte-loss sessions or not), whether §6
item 3 should be revised host-only for recovered retries (a v0.5, reviewed and re-frozen
before any ruling), and the ≈2 s chunk timeout. No board contact and no ruling until the
owner rules.

## 2026-09-02 — owner's rulings on C1 #5: push approved; stop-loss TRIGGERED (S #1 + C1 #5); v0.5 host-only design batch authorised (C1 #5 not re-judged); reader-residue fix authorised — delivered host-only

The owner's review: C1 #5's HOLD (instrument) is correct, the evidence credible, not
pinnable. Four rulings. (1) Push `3e32f7a` — done, `origin/main = 3e32f7a`; the owner's
own run: 864 tests, no failure. (2) Stop-loss: S #1 and C1 #5 are two consecutive
sessions lost to the same instrument/transport failure class — contiguous byte deletion
on the same console path; S #1 on a REC ended the session, C1 #5 on an AUDIT was
recovered by rec-v3 but the recovery itself put the CoV over the bound; the different
frame types and consequences do not change the observable failure class. A classification
under frozen §7 (`docs/l6_soak_prereg.md` line 316), not a claim of a proven common
physical root cause: no next board ruling; C2, S and Claim B stay paused. (3) A host-only
v0.5 design batch is authorised, but NOT one that merely excludes the retried period to
turn C1 #5 into a PASS: C1 #5 stays HOLD under v0.4 permanently and `calibration.C1`
stays null. v0.5 separates an inclusive rate (all steady-state periods, recoveries in —
the value S's N is derived from) from a nominal CoV (periods without a transport
recovery) that is bounded only with a preregistered minimum clean sample; independent
recovery/loss indicators with bounds (timeouts, BAD_FRAME, CRC drops, retries, exposure)
so a nominal CoV cannot hide an unstable link; every raw period and retry kept; C1/C2
re-run under v0.5, no old pin reused. (4) The timeout may be studied but not merely
re-pinned: the real host defect is `host/l6_reader.py` keeping an unterminated residue
for ever so the resend glued to it; shortening `l6_audit_pull.CHUNK_TIMEOUT_S` alone
would only resend earlier into the same BAD_FRAME. Authorised host-only scope: quarantine
(never silent drop) of the residue on timeout/retry, resync on a new `P3L5` frame head,
a monotonic deadline instead of `tick(0.02)` accumulation, a replay of C1 #5's raw bytes
proving the first resend recovers, discrimination tests (truncation, late tail, glue,
duplicate, an ordinary half line across polls), a pure host replay/fault-injection soak,
then review. The owner's round-trip figures over 520 clean chunks (median 42.9 ms, p99
83.1 ms, max 83.6 ms) match ours (528: 42.9 / 83.1 / 83.6): 2 s is long, ≈0.5 s a
candidate for validation, not pinned now. rec-v3 proved that an audit re-request keeps a
whole epoch — valid engineering evidence — but other board→host frames are still not
re-requestable, so no new board session or ruling before a complete transport/protocol
review.

Delivered the same day, host-only (`docs/l6_transport_batch_package.md`): reader resync
on a frame head + fragment quarantine with FRAGMENT events in the timeline ledger; the
pull's monotonic chunk deadline, timeout callback before the retry, stale byte-identical
replies ignored; the runner hands the reader and clock to the session and selects the
PASS rule by the manifest's prereg version; rate report 1.1.0 with inclusive / nominal /
recovery (C1 #5: 0.274 / 0.056 over 62 with seq 39 excluded; 1 recovered candidate, 1
timeout, 1 bad frame, 0 fragments); `calibration_findings_v05` naming every crossed
bound; prereg v0.5 DRAFT (`docs/l6_soak_prereg_v0.5_draft.md`, D-t1..D-t3, §6 items
3/3a/3b/3c, §7 records the stop-loss) with the draft bounds in the manifest's
`next_prereg`; C1 #5's recorded bytes replayed — new reader + pull: chunk 1 `[timeout,
ok]` (glued in one read: `[ok]`, no timeout), the C1 #5 reader: the recorded `[timeout,
malformed, ok]`; the seeded soak over 2000 candidates × 5 configurations — every single
fault of every kind recovered on the first resend at 2.0 s and at 0.5 s, pulls failing
only on retry exhaustion, no clean candidate marked; the C1 #5 reader on the same seed:
truncations recovered first-resend 21/499, 1530 bad frames, 247 failed pulls. The
timeout stays 2.0 s (D-t3 proposes ≈0.5 s for the owner). Nothing re-judges C1 #5; no
board, no ruling, no freeze, stop-loss standing.

## 2026-09-02 — owner's review of the transport batch: PASS (host transport fix, scoped) / HOLD (v0.5 freeze, return to the board); three freeze blockers; D-t3 pinned at 2.0 s; stop-loss NOT lifted — correction batch delivered host-only

Rulings. (1) Push `b58d0fd` — done, `origin/main = b58d0fd`; the owner's own run 897 tests
green. (2) Three blockers before any freeze: `host/l6_rate.py` produced nominal/recovery
figures from half a ledger set (the other half's faults counted as zero) — v0.5 must
require both present and valid; the rate report bound only the run log's hash, not
`audits.json`/`timeline.json` — the three files' actual sha256 must be recorded and
verified by the later calibration pin; the "inclusive" rate took only the 63
interior→interior periods, so a recovery on the last candidate (falling in the
last→closing transition) is excluded and "a recovering link gives a smaller N" does not
hold — a truly conservative planning rate is needed, e.g. from the full bracketed session
span, with a last-candidate counterexample test; and the draft's "As v0.4" deltas must
become a self-contained text at the freeze. (3) D-t1 accepted in principle (S from a
recovery-inclusive conservative planning rate once the last-period gap is closed); D-t2
accepted (attribution; both ledgers; input hash binding); **D-t3: 2.0 s pinned** — 0.5 s
not adopted, the simulation shows it works but nothing shows the real CH340/usbipd path
is safe under a host scheduling stall. (4) v0.5 not frozen until the blockers and the
self-contained text are done and re-reviewed; C1 #5 stays HOLD under v0.4, never
re-judged. (5) The stop-loss is not lifted: the host soak proves the model and the
mechanism, not the physical path, and `SIGNREQ`, `HB`, `AUDIT_READY`, `CLOSE`, `TERM` are
still not re-requestable and can end a 2 h soak through the same byte-loss family.
Therefore: no C1 ruling; C2, S, Claim B paused; a host-only correction batch may close
the three blockers, produce the self-contained v0.5 text and propose a complete
reliability design for the non-re-requestable frames; firmware/protocol/image changes
are ruled separately after that design is reviewed.

Delivered the same day, host-only (`docs/l6_transport_batch_package.md` §8): both
ledgers or neither with shape and coverage checks (`_check_ledgers`; the CLI refuses a
half set); `inputs` = sha256 of the three files as written, the runner hashing them after
writing, `calibration_inputs_findings` at the S import, refusal under v0.5 of a report
without inputs or planning; the planning rate (candidates over the bracketed span; C1 #5:
3508.9 vs inclusive 3607.8 vs nominal 3734.4) and `plan_session` sizing S from it under
v0.5 (`rate_source` recorded); the last-candidate counterexample as a test (closing
bracket shifted 2 s + a FRAGMENT in seq 65's window: inclusive/CoV identical, planning
lower, recovered_seqs [39, 65], nominal excludes [39] only); rate report 1.2.0;
`docs/l6_soak_prereg_v0.5_draft.md` rewritten self-contained with D-t3 recorded as ruled
and the stop-loss ruling in §7; `docs/l6_frame_reliability_design.md` (exposure: 24.8 MB
per soak, 33 % in non-re-requestable frames, ≈7.5 fatal-class events expected under the
per-byte reading; per-frame proposals SIGNREQ transaction + idempotent reply cache,
AUDITREQ in SIGNOK, AUDIT_READY resend, indexed HB with a budget, CLOSE in TERM, TERM
transaction, IDENT repeat; host-only parts first behind a protocol switch, one firmware
batch → v0.6). `tests/test_l6_rate_v05.py` (14). No board, no ruling, no freeze; the
stop-loss stands.

## 2026-09-02 — owner's review of the correction batch: PASS (D-t1; the correction line) / HOLD (design, four items); v0.5 NOT frozen — straight to v0.6; two D-t2 fail-closed fixes; the rel-v4 host batch authorised and delivered

Rulings. (1) Push `62d2922` — done, `origin/main = 62d2922` (owner's run: 911 green).
(2) D-t1 accepted (planning = 64 × 3600 / bracketed span). D-t2 accepted with two
fail-closed corrections: the ledger check compared sets and let a duplicate REC/pull
ledger through (a later dict would keep the last) — exactly one REC ledger per seq, at most
one pull ledger per seq, extra seqs refused; and the runner hashed the files on disk but
computed the report from in-memory ledgers — the report must be computed from the three
files as read back (one entry point). (3) v0.5 is NOT frozen: it still runs on rec-v3,
which cannot survive a long soak, and a C1/C2 under it would have to be re-run after the
reliable protocol and new image; v0.5's three rates, planning, recovery and input binding
merge into v0.6 without an executable intermediate. (4) The reliability design: HOLD on
four items — a lost AUDITDONE was still unrecovered (host audited / board replayed-only);
"IDENTACK or the first sign reply" is unsafe, the handshake must complete before the first
SIGNREQ; STOP_SIGN lacked its evidence contract (a signed request with no record, orphan
notary entries, nonce consumption, validator rules); the "negligible" independence-based
residual figure is unsupported by five events and must go; the HB 99.9 % needs its integer
rounding and denominator pinned. (5) Stop-loss stays TRIGGERED; no C1/C2/S/Claim B ruling.
Authorised: a host-only batch closing D-t2 and the four gaps, implementing the v0.6 host
state machines, caches, validator and twins behind a new protocol switch with rec-v3
proven unchanged, and per-frame loss/duplication/truncation/exhaustion tests. The firmware
batch is formally opened but starts only after this batch is reviewed PASS; then a new
image, a full P3 compatibility review, the self-contained v0.6 prereg and its freeze; then
ONE C1 → C2 → S.

Delivered the same day, host-only (`docs/l6_rel_batch_package.md`): D-t2 — duplicate
ledgers refused by seq, `rate_report_from_evidence_dir` the only entry point (the runner
calls it after writing run_log/audits/timeline; the CLI calls it); rel-v4
(`host/l6_rel.py`): IDENT handshake verified before the acknowledgement and completed
before the first SIGNREQ (a SIGNREQ without it is PROTOCOL_IDENT), the SIGNREQ transaction
with one signature per seq and the cached reply replayed (notary `replays`), SIGNGET on a
broken request, `audit_requested` folded into SIGNOK (no AUDITREQ frame), AUDIT_READY
resent on the bound, the AUDITDONE handshake (AUDITWAIT → the same DONE replayed; exhaustion
= STOP_AUDIT on the board and `unconfirmed` on the host), indexed heartbeats with the
budget ⌊R/1000⌋ over R = SCORED records and never two missing per record, CLOSE
reconstructed from TERM's `closing_control`, the TERM transaction (TERMACK/TERMGET,
re-ack after the end); the validator's STOP_SIGN contract (terminal; `sign_stop` only;
replayed-only; no nonce step; a notary entry behind it is not an orphan) and rule (vii-b)
(an app-written epoch leaves no notary entry without a record; a crash may); the
ConsoleSession switch `protocol="rel-v4"`, the runner selecting the protocol from the
pinned image (`HOST_PROTOCOLS`, prereg/image must match), `l6_schedule.PROTOCOLS["rel-v4"]`,
the timeline's `hb_i`, `structural_findings(protocol)`; `tests/test_l6_rel.py` (38: every
frame lost / corrupted / duplicated / torn through the real reader / exhausted; the session
end to end; rec-v3 unchanged; the validator); the design revision 2 with the four items
closed and no probability attached; `docs/l6_soak_prereg_v0.6_draft.md` self-contained
(v0.5's content carried verbatim, §2.6i–6p, D-p1, §4.19–23, §6.10–13), the v0.5 draft
marked superseded, never frozen. No firmware, no image, no board, no ruling, no freeze.

## 2026-09-02 — owner's review of the rel-v4 host batch: HOLD (seven integration items); D-p1 bounds accepted with exact semantics; 866bc5b not pushed; firmware batch not yet authorised — correction batch delivered host-only

The owner's HOLD, each reproduced on the real `ConsoleSession`: (1) the AUDITWAIT ledger
written to audits.json was a stale settle-time copy; (2) `unconfirmed` was set on the
third WAIT while the third replay could still succeed (board SCORED/audited vs host
unconfirmed); (3) the TERM re-ack branch was unreachable in the real runner (the collector
ends the epoch on the first TERM, the runner leaves its loop); (4) IDENT wiring off the
design: a CRC-bad IDENT not ledgered, a malformed one CRASHED, a refused identity ended the
epoch at once instead of the board exhausting to STOP_IDENT; (5) v0.6 §6.10–13 not
machine-enforced (no rel closure, no SIGNREQ-control shape, no sign_retries /
ready_resends / ident_repeats / term_retries / done_replays with bounds); (6) STOP_SIGN
accepted by the validator under a rec-v3 identity; (7) CLOSE and TERM's closing_control
not compared when both exist. D-p1 accepted: 3 board transmissions in all (first + 2
resends), host GET ≤ 2, WAIT ≤ 3, replay/re-ack ≤ 3 — but the third WAIT is not a final
failure; the board's closure evidence decides. Rulings: 866bc5b not pushed; rel-v4
host/design HOLD; a host-only correction batch closing the seven items with real
ConsoleSession / runner-lifecycle negative tests; firmware/image, v0.6 freeze, rulings and
board work still not authorised.

Delivered the same day, host-only (`docs/l6_rel_batch_package.md` §8): pull ledgers
rendered live (`ConsoleSession.pull_ledgers` property, `waits_exhausted` a fact); no
host verdict on waits — `rel_closure_findings` reads the board's record; the runner's loop
condition `session_loop_continues` lingering 22 s after the first TERM under rel-v4 (a
resent TERM re-acknowledged; rec-v3 unchanged); IDENT broken lines ledgered before the
collector, a refusal = no ack + no host end + `refused` ledger (the board's STOP_IDENT TERM
ends the epoch; the refusal a closure finding), a SIGNREQ after a refusal PROTOCOL_IDENT;
`rel_closure_findings` / `rel_control_findings` / `rel_recovery_findings` +
`recovery_by_seq` rel indicators (one per non-ok attempt) + `rel_session_totals` +
`FLAG_SIGN_CONTROL`, all called by the runner under rel-v4, bounds in the manifest's
`rel_pass_conditions_draft`; STOP_SIGN refused unless the IDENT declares rel-v4; CLOSE vs
TERM compared, a disagreement recorded and named. `tests/test_l6_rel_correction.py` (14)
on the real session and the loop condition; design revision 3; the v0.6 draft updated
(§2.6j/6m/6o, D-p1 as ruled, §4.21–22, §6.10/12/13). No firmware, no image, no board, no
ruling, no freeze.

## 2026-09-02 — owner's second review of the rel-v4 batch: HOLD (two acceptance blockers, two pins before firmware, two minor); D-p1 semantics accepted; push and firmware still withheld — second correction batch delivered host-only

The seven items' main paths confirmed; two new host acceptance blockers: (1) sign ledgers
could still last-wins — dict comprehensions in `rel_closure_findings` and the rate
collapsed two same-seq ledgers silently (two identical seq-1 ledgers passed the closure);
(2) an app-written TERM without `closing_control` passed when a CLOSE existed. Before the
firmware batch: (3) `flags.bit5` had no IDENT echo / verification; (4) the 22 s TERM linger
assumed a 10 s board bound without a verifiable relation to the C poll count. Minor: a
different second IDENT after a refusal was logged as a repeat; the heartbeat comment
misstated the 99.9 %. Rulings: no push, D-p1 semantics accepted, no firmware start; a
limited host/spec correction batch; board, rulings, freeze still forbidden.

Delivered the same day, host-only (`docs/l6_rel_batch_package.md` §10): `unique_ledgers_by_seq`
(exactly one sign ledger per seq, the seq set equal to the record set, duplicates /
missing / extra named, never last-wins) shared by the closure and the control check and
refused by the rate; `l6_rel.closing_control_findings` (the complete typed block mandatory
for every app-written TERM; rebuilt only from a complete block; both present must agree);
IDENT 1.3.0 `sign_retry_control` verified by `check_l6_identity` under rel-v4 at both
checks; `BOARD_BOUND_WALL_MAX_S` = 10 s + `FIRMWARE_BOUND_CONTRACT` (the five poll-count
bounds, the proof named) with `TERM_LINGER_S` derived from it and the v0.6 draft §2.6p
stating it as an unverified contract until the firmware batch; refused-repeat compares
bytes; the heartbeat docstring corrected. `tests/test_l6_rel_correction2.py` (11), the
v0.6 draft (§2.6d/6o/6p, §6.10, §4.22), design revision 4 (● marks). No firmware, no
image, no board, no ruling, no freeze.

## 2026-09-02 — owner's third review of the rel-v4 batch: HOLD on one narrow blocker (the rate accepted a rel-v4 report without sign ledgers) — closed host-only

The six second-batch corrections confirmed. The remaining gap: `l6_rate._check_ledgers`
checked sign ledgers only when `audits.signs` was present, so a rel-v4 calibration with
the key missing or null was accepted with `sign_retries` 0 (reproduced on C1 #5's
evidence with the identity set to rel-v4) — a tampered input set could re-hash itself
consistent and drop the SIGN recovery. Rulings: package §10 HOLD on that gap only; no
push; no firmware; a minimal host/test/docs correction, then the shortest review, then
push and the firmware batch with the IDENT 1.3.0 echo and the board-bound contract proof
as mandatory deliverables.

Delivered: `_check_ledgers` takes the session protocol from the run log; under rel-v4
`signs`/`ident`/`term` must exist (signs a list, null refused; ident an object; term an
object or null) with the one-per-seq and seq-set checks unchanged; rec-v3 needs no
`signs`; non-integer seqs anywhere are `RateError`s. Tests through the real
`rate_report_from_evidence_dir()` on a copy of C1 #5's evidence: key deleted, null, one
missing, one duplicated, a non-integer seq, `ident` missing — refused; rec-v3 without the
key passes (`docs/l6_rel_batch_package.md` §12).

## 2026-09-03 — owner's fourth review: package §12 PASS (host-only scoped); push of the four commits approved; the firmware batch opened with mandatory deliverables — delivered host-side: the rel-v4 image as next_image, NOT board-ready

The owner: the rel-v4 rate gap closed through the real disk entry point; missing / null /
short / duplicate / extra / non-integer sign ledgers all fail closed; ident/term checked;
rec-v3 evidence unchanged. Rulings: package §12 PASS; push 866bc5b, e2c0caf, e61e994,
a8c950d (done, origin a8c950d); the firmware batch may start with mandatory deliverables —
IDENT 1.3.0 + the bit5 echo; the five poll-count bounds pinned with a source audit, the C
twin and the manifest; proof that every board bound is ≤ 10 s on the pinned clock (host
timing of the twin is not that proof); C twins for the IDENT refusal, the AUDITWAIT counts
and the CLOSE/TERM redundancy; two from-scratch byte-identical builds; next_image with
board_ready false, then the full P3 compatibility review. No freeze, no ruling, no board.

Delivered 2026-09-03 (`docs/l6_rel_firmware_package.md`): `p3_rectx.c` generalised
(`p3_tx_run` with ack/get kinds, the strict previous-ack rule, `p3_rectx_recv_line_timed`
bounded by polls AND global-timer ticks — whichever first), `p3_pull.c` (READY resent ≤ 3
while no GET, AUDITWAIT ≤ 3 after the last chunk), `p3_app.c`: IDENT handshake before any
SIGNREQ (STOP_IDENT on exhaustion; the SIGNREQ is never sent), the SIGNREQ transaction
(STOP_SIGN terminal record; audit_requested read from SIGNOK; no AUDITREQ frame; the seq-1
control on flags.bit5), the pull through the unit, indexed heartbeats, the closing control
kept for the TERM, the TERM transaction, the global timer started once at go and every
wait bounded by `P3_BOUND_TICKS` = 8 s × COUNTS_PER_SECOND (333,333,343 Hz on the pinned
6:2:1 clock; the poll caps a termination backstop); `p3_wire.c`: IDENT 1.3.0
`sign_retry_control`, HB `{i}`, TERM `closing_control` when reached, `sign_stop`. Twin:
`identtx`/`signtx`/`termtx`/`pulltx` over a pipe with the injected clock. Tests:
`tests/test_firmware_rel_contract.py` (17, the real IdentHost/SignHost/TermHost/PullHost
driving the C code), `tests/test_firmware_rel_audit.py` (12: the source-derived bound proof
8 s ≤ 10 s, the timed receiver, the transactions, purity, heartbeats, identity); the old
audit/contract suites updated to the new structure. Two from-scratch builds byte-identical:
bin `734d6c04895e81d5fef3196f7b3298d03a7c6c6d3b9fe3f35abc9cc0b1e323b1` (98 324 B), ELF `a2a422157aaf1f66…` → `manifests/l6_manifest.json` `next_image`,
`board_ready: false`, `bound_contract` pinned; `evidence/l6_next_build/` regenerated (the
cd8360dc… and e19e1b12… records preserved). Not run on hardware; the full P3
compatibility review is the owner's; no freeze, no ruling, no board.

## 2026-09-03 — the rel-v4 firmware package: full P3 compatibility review HOLD; `734d6c04…` withdrawn DEFECTIVE; the corrected image `5deee74c…` delivered for a short re-review

The owner's review of `docs/l6_rel_firmware_package.md` (commit `6c72db9`, not pushed):
HOLD — no push, no promotion, no v0.6 freeze, no ruling, no board. Blocker 1:
`p3_pull.c` accepted an `AUDITDONE` with zero or partial chunks served (and Python
`PullBoard` did the same) — an incomplete audit could be marked `audited` and reach ARM;
required: C and Python negative tests (zero chunk, partial chunk: no success, no `audited`,
no ARM). Blocker 2: the timed receiver's whole-line wall-time bound was `idle_ticks × 4` =
32 s (`line_ticks = idle_ticks * P3_RECTX_LINE_POLL_FACTOR`) — the idle AND the whole-line
maximum must both be ≤ 10 s, with source-derived and injected-clock trickled-line
counterexamples. Contract defect: `AUDITWAIT.served` counted transmissions
(`chunks_served`), not unique chunks — it must be the popcount of `served_mask` and equal
`chunks` in the all-served branch. Also: the contradictory `next_prereg.status` sentence in
`manifests/l6_manifest.json`. Recommendation adopted: `734d6c04…` DEFECTIVE — must not run;
rebuild; discrimination tests; package updated; short re-review. The stop-loss stays
triggered; board and rulings stay forbidden.

Delivered (package §7): `p3_pull.c` — an `AUDITDONE` before every chunk was served aborts
the pull fail-closed (`why` "AUDITDONE before every chunk was served: the audit is not
complete"; no `done`, so no `audited`, no ARM), `AUDITWAIT.served` = popcount(served_mask);
`host/l6_audit_pull.py` `PullBoard` the same refusal (`STOP_AUDIT`); `p3_rectx.c`
`line_ticks = idle_ticks` (the ×4 factor stays on the poll-count backstop only), so one
receive ends within one bound however the bytes are paced; the twin's clock now ticks on
EMPTY polls only (a waiting byte costs no time, as on the board a whole line arrives in
milliseconds against 8 s) and gained `!trickle N text` (N empty polls before every byte).
Tests: `tests/test_firmware_rel_contract.py` (21): DONE with zero and with 7/8 chunks →
`aborted`, `done 0`, the why; the Python twin the same; a repeated GET for chunk 0 → AUDITWAIT
`served 8` while `gets 9`; `!trickle 60` (660 ticks, accepted as a line under the old 1200)
abandoned as partial within 300 and resent, `!trickle 10` still a line;
`tests/test_firmware_rel_audit.py` asserts `line_ticks = idle_ticks`, the absence of the ×4
tick product, and the worst path ≤ 10 s; `tests/test_l6_rel.py` (39) the Python early DONE.
Two from-scratch builds byte-identical: bin
`5deee74c44785ebe88168ccffaa5f399f26a7c5a567fccb3d430cf4eb14cdc7c` (98 324 B), ELF
`ebe97ce6a591bad6…` → `next_image` (`board_ready: false`); `734d6c04…` (ELF `a2a42215…`)
appended to `withdrawn_images` with the three findings; its build record preserved as
`evidence/l6_next_build/build_evidence_734d6c04.json` + `p3_app_l6_734d6c04.map`; the
`next_prereg.status` sentence rewritten; `bound_contract.whole_line` pinned. Not run on
hardware; the short re-review is the owner's; no push, no freeze, no ruling, no board.

## 2026-09-03 — short re-review of the rel-v4 firmware §7: three fixes PASS, HOLD on one evidence-closure blocker; archived build records closed

Owner (2026-09-03): B1 / B2 / C PASS at the source and on the twin (`gets 9 served 8
mask 255` reproduced); image and live evidence PASS (bin `5deee74c…`, ELF `ebe97ce6…`,
map `a0dab213…`); suite 1014 OK. HOLD: `evidence/l6_next_build/build_evidence_734d6c04.json`
pointed its map at the live `p3_app_l6.map` (`a0dab213…`, not the recorded `4d07230f…`)
and its binary at the live `out/p3_app_l6.bin`, which can no longer verify to `734d6c04…`;
package §7's "preserved" claim therefore substantive; and the withdrawn-list exact guard
sat in the `next_image is None` branch and did not run. Required: archived map paths →
archived maps; the old binary archived or declared hash-only, never a live path; a
fail-closed test that every archived record's non-empty artifact path exists and hashes;
the exact-set guard on both branches. No firmware change, no rebuild; then an extremely
short evidence-closure review; no push / promotion / freeze / ruling / board before it.

Delivered (package §8): the defect was in all five archived records (`l6_next_build`
`734d6c04`, `cd8360dc`, `e19e1b12`; `l6_build` `bd1454cd`, `e19e1b12`) — each now names its
archived map, declares its binary "historical artifact unavailable — hash-only" (the
binaries were never preserved; out/ is gitignored and rebuilt) and carries an `archived`
block (date, why, the original paths, `hashes_unchanged: true`); no hash changed.
`tests/test_package_consistency.py`: `BuildEvidenceClosure` (5 tests over the 8 records:
map path exists and hashes; cited report exists and hashes when a hash is recorded;
binary hashes or is the marker with an `archived` block — a live path in an archived
record fails; archived records named by their image and naming their archived map);
`test_one_image_one_authority` asserts the exact superseded/withdrawn sets and the pin on
both branches, and with a candidate that it is not withdrawn and the live next-build
evidence is its. The closure test also caught the live record of the board-ready pin
(`evidence/l6_build/build_evidence.json`, `403f4ab5…`): its binary path resolved to the
candidate HEAD builds; no `403f4ab5…` binary exists on disk, so it is hash-only with a
`binary_unavailable` block. Image, manifest and `next_image` unchanged. No push, no
freeze, no ruling, no board.


## 2026-09-03 — owner's promotion/freeze batch (host-only): `5deee74c…` promoted to the sole rel-v4 `pinned_at_build`; `403f4ab5…` superseded NOT defective; prereg v0.6 FROZEN; stop-loss stays TRIGGERED

Owner (2026-09-03), after the evidence-closure review PASS and the push of `6c72db9`,
`b3806ad`, `57cc22b`: a single host-only batch opening promotion and the v0.6 freeze — not a
board authorisation; the stop-loss stays TRIGGERED. Scope as pinned by the owner: (1) image
authority — `5deee74c…` the only `pinned_at_build`, protocol rel-v4, `board_ready: true`;
`403f4ab5…` into `superseded_images` marked NOT defective with its C1 #5 and v0.4 history
kept; `734d6c04…` stays withdrawn DEFECTIVE; the `next_image` entry removed; build evidence
and BIN/ELF/MAP hashes still closed, no firmware rebuild. (2) v0.6 frozen — the
self-contained draft promoted to `docs/l6_soak_prereg.md`, its hash into the manifest with
`version = v0.6`, `protocol = rel-v4`; v0.4 `12799ef9…` into the supersedes chain, its
historical text not rewritten; `calibration.C1/C2` null; the pull-v2 and rec-v3
calibrations history only, never S's input. (3) the draft's present-tense drift corrected
before freezing: design revision 4 (not 2); the firmware batch delivered with its
compatibility review / correction / evidence closure all PASS (not "not yet started");
`5deee74c…` the promoted pin (no longer a candidate with `board_ready: false`); no
"waiting for the package §7 short re-review"; package §8's final standing = the
evidence-closure PASS with the HOLD kept as history; the manifest's `next_prereg` review
state moved into a clear history chain (`prereg.supersedes`, `prereg.never_frozen`,
`prereg.draft_history`). A freeze-time guard refuses those stale phrases as the present in
the frozen v0.6. (4) stop-loss — TRIGGERED throughout; a conditional lifting only after the
frozen-artifact short review passes, opening ONE rel-v4 C1 and nothing else; C2, S and
Claim B not opened in advance; C1 #5 permanently HOLD under v0.4, not re-judged.

Delivered: `manifests/l6_manifest.json` (`pinned_at_build` = `5deee74c…` / ELF `ebe97ce6…` /
98 324 B / rel-v4 / board-ready, `wire` + `bound_contract` carried from the candidate entry;
`403f4ab5…` appended to `superseded_images`; `promoted_note`; `prereg` = v0.6 / rel-v4 / the
new sha with `supersedes` v0.4 → v0.3 → v0.2, `never_frozen` v0.5, `draft_history`; the
draft's bounds merged into `pass_conditions`; `calibration.historical_rec_v3`; the two
control bits on the identity page; `sessions.S.n` in planning rates; `status`).
`docs/l6_soak_prereg.md` = v0.6 FROZEN (from the draft with the drift replaced; §7 carries
the freeze-time stop-loss record); `docs/l6_soak_prereg_v0.6_draft.md` marked MERGED /
HISTORICAL, body verbatim. `evidence/l6_build/`: the `403f4ab5…` record archived as
`build_evidence_403f4ab5.json` + `p3_app_l6_403f4ab5.map` (archived block, hashes
unchanged); `build_evidence.json` + `p3_app_l6.map` regenerated for `5deee74c…` from the
unchanged `out/` build (byte-identical to the pin). `docs/l6_rel_firmware_package.md`
standing and §8 final standing; `docs/l6_frame_reliability_design.md` standing note;
`tests/test_package_consistency.py`: the authority guard (rel-v4, three superseded, three
withdrawn, no `next_image`/`next_prereg`), the v0.6 present-tense guard (`FROZEN
2026-09-03`, rel-v4, the pin, the history chain), the stale-phrase guard over the frozen
text, the manifest's standing strings and the package's standing block, the history-chain
guard (supersedes, never_frozen, merged bounds, the archived 403f4ab5 record);
`tests/test_l6_transport.py`, `tests/test_l6_rel_correction.py`,
`tests/test_l6_rel_correction2.py`, `tests/test_l6_rate_v05.py` re-pointed at the frozen state
(the rate-v05 soak fixture now binds its manifests to the C1 #5 report's own pins). Suite:
1021 tests / 1 skip / rc 0 twice — A `evidence/tests/test_report_2026-09-03T142624Z.json`
(cited by the build evidence), B `…142636Z` (final); the run before them, `…142352Z`, failed
on the two new evidence files not yet tracked and on that fixture, and is kept as recorded.
Firmware bytes unchanged
(bin `5deee74c…`, ELF `ebe97ce6…`, map `a0dab213…` on disk = manifest = evidence). No
ruling, no board contact, not pushed: the frozen-artifact short review comes first, then
the push decision and the first rel-v4 C1 ruling pair.

## 2026-09-03 — owner's frozen-artifact short review: PASS; `d836107` pushed; stop-loss conditionally lifted for ONE rel-v4 C1; C1 #6 (ruling 2026-09-03-01) = PASS (runner outcome)

Owner (2026-09-03): the frozen-artifact short review of `d836107` = PASS (prereg
`bfd69d10…`, manifest `1746cdfa…`, BIN `5deee74c…`, ELF `ebe97ce6…`, MAP `a0dab213…` all
verified; HEAD = worktree; one board-ready rel-v4 authority; `403f4ab5…` superseded NOT
defective; the three withdrawn exact; the v0.4 → v0.3 → v0.2 chain, v0.5 never frozen and
the calibration isolation hold; the frozen v0.6 free of the 19 stale phrases; the runner's
real pins reach the boundary gate; 1021 tests OK with an environment-only extra skip;
firmware/host/validators unchanged against `57cc22b`). Non-blocking note: the standing of
`docs/l6_frame_reliability_design.md` still opens with the old "nothing implemented in
firmware" sentence before the note that it is history. Push of `d836107` approved and
done (`origin/main` = `d836107`). **Stop-loss ruling:** conditionally lifted for ONE
rel-v4 C1 only — C2, S and Claim B not opened; a non-PASS C1 is archived and returns to
the owner, never re-run; a PASS C1 is reviewed and `calibration.C1` pinned before C2 is
discussed; C1 #5 not re-judged. Ruling pair `2026-09-03-01` issued (whole-of-probe
P3-L6, C1, seed 1278624577; provisioning P3-K; both bound to the three hashes above).

Executed in order: push → origin/HEAD/tree/hash check → the pair written verbatim →
power cycle (owner; UART re-enumerated 15:46) → boundary verifier R1–R5 PASS
(`evidence/boundary/principal_boundary_2026-09-03-01.json`) → `host/l6_runner.py` in the
background (pid 13152, waited on by pid). **C1 #6 = PASS (runner outcome, 15:53):**
IDENT 1.3.0 rel-v4 with both control bits echoed, one transmission, one IDENTACK; 66
SCORED (1 + 64 + 1), baselines exact, closing control fault 13 carried by TERM and CLOSE in
agreement, TERM COMPLETED / budget; 66/66 audits pulled and verified, zero pull retries,
timeouts, waits or replays; 1785 inbound frames = expected; CRC drops 2 of 8 = the SIGNREQ
and REC controls, each ledger exactly `["crc", "ok"]` with one SIGNGET / one RECGET; 0 bad
frames, 0 fragments, 0 recoveries; `findings: []`; rate report
`08222f85799fa3d18012cdd26a5cc047527995b682bfd5679a668014ea03251c` = 3495.7 evals/h
inclusive (CoV 0.0151 over 63/63 clean periods), planning 3381.4 evals/h, bound to the
session's pins and its three input files. Both rulings consumed (PASS). Archived:
`docs/l6_c1_session6_findings.md`, manifest `hardware_history` (66/1/64/1) + standing
(5deee74c… RAN ON 17A6) + status, `docs/status.md` row, import manifest. Nothing pinned
here: `calibration.C1` stays null until the owner adjudicates and pins the report by hash;
C2 needs its own ruling pair bound to the post-pin manifest and a power cycle. No push.
