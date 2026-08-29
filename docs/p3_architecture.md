# P3 — re-establishing the write-integrity interlock around a PS-side oracle

> **HOST-SIDE ARCHITECTURE DRAFT. Nothing here is evidence, nothing here authorises a
> board action, a ruling, a Vivado build, or a change to `zynq-psmap` or `zynq-fabricmap`.**
> Owner authorisation of 2026-08-29 covers exactly: this repository's boundary, this
> document, the acceptance ladder, the three-party authority model, the definitions of
> `configuration_valid` / identity / epoch, the schema contracts, D1, and kill criteria.
> Everything else waits for cross-review and a separate ruling.

Status: **draft v0.2, 2026-08-29** — §3 rewritten on Option A′ after the L0 REJECT of v0.1 (`l0_review_result.md`) and the owner's conditional acceptance of A′ (`p3_enforcement_proposal.md`). Author: Claude. **Reviewed 2026-08-29: §3 v0.2 ACCEPTED as the L0 architecture basis, all four questions ruled (`l0_review_result.md`); L0 overall not passed until the exit deliverables exist. L1 condition: every ARM entry point behind the MAC gate, negative testbenches never `armed`, no readable path to `K`.**

## 0. The one question P3 exists to answer

`zynq-fabricmap/docs/claimb_findings.md` §3.5 (at `71666b02`):

> replacing links 2–3 with a stronger oracle is **legitimate in principle** … but that
> legitimacy requires a **new, reviewed hardware architecture** in which the interlock is
> re-established rather than removed. **Direct bypass remains invalid.**

and §7, what would reopen the paused Claim B programme:

> a **new, reviewed measurement architecture** in which the write-integrity interlock is
> re-established around an oracle that can actually observe non-blank content.

`zynq-psmap` has since measured, on `17A6`, the three properties such an oracle needs
(`s1s3_findings.md`, `p1_findings.md`, `p2_findings.md`, all at `191ab05`):

| property | measured | scope |
|---|---|---|
| PS/PCAP reads a setup-loaded non-blank frame bit-exactly and repeatably, with no shutdown transition | S1–S3 PASS, run #3 | `17A6`, U-Boot, `0x00000B99`, ten reads |
| PS/PCAP writes a certified content-bit change and reads it back bit-exactly; an independent instrument (JTAG R4) confirms the frame | P1 PASS, run #1 | `17A6`, U-Boot, `0x00400A20` word 51, blank→A→B |
| Ten PCAP reads of a live-logic frame and one content-bit write leave the carrier's eight readable registers unchanged, against a matched no-read control | P2 PASS, run #3 | `17A6`, the eight registers, stable-state class only |

**P3's question:** *can an interlock with the same three links as the carrier's — accepted
bytes == delivered bytes == fabric bytes — be re-established with the PS as the witness of
links 2 and 3, such that a candidate is scored only when all three links have been
checked by an instrument that observed the actual bytes, and such that nothing in the
architecture is a match bit the host has to take on trust?*

It is an architecture-and-instrument question. It is **not** Claim B: Claim B's arms,
budget and preregistration stay in `zynq-fabricmap`; P3 delivers the instrument that
programme was waiting for (§9).

## 1. What P3 inherits, and from where

Everything below is consumed as a **versioned artifact** (`docs/contracts.md`), imported
byte-for-byte with its source commit when the ladder reaches the stage that needs it —
never as a live path into a sibling tree (`zynq-ehw/docs/future_plan.md` §"Inter-Project
Contracts"; `zynq-autoehw/docs/workflow.md` rule 5).

| from | what | why |
|---|---|---|
| `zynq-psmap` `191ab05` | `board_session.py` (one transport, identity, epoch, guarded replies, md.l re-read policy), `pcap_probe_plan.py` + `pcap_probe_runner.py` (the pinned read and its guards), `pcap_write_plan.py` + the P1 write path, `p2_observe.py` (AXI allowlist, FCLK0 decode, continuity rule), `frame_ecc.py`, `probe_jtag_config_read.py` + cfg (R4 terminal verifier) | the PS oracle **is** these instruments; they are board-proven and their guards are the ones review already accepted |
| `zynq-fabricmap` `71666b02` | `gate_candidate.py` (link 1: the 292-bit whitelist, flush frames verbatim, ECC recomputed — the host gate), `local_map.json` + certificates (what is certified), the carrier's scorer RTL and its testbenches as the starting point of the P3 carrier, `run_log` hash domains, `claimb_preregistration.md` (control-plane boundary) | link 1 is unchanged; the scorer is reused; the preregistration constrains what P3 may claim |
| `zynq-autoehw` `8882613` | `docs/schema.md` compatibility policy; the M1 paged mailbox heartbeat contract (`m1_board_handoff.md`) | the schema discipline; the counter-class observable P2b needs |

## 2. The three parties, and what each may and may not decide

```
            host gate (link 1)          PS oracle (links 2, 3)         PL scorer
            ──────────────────          ──────────────────────         ─────────
 decides    is this candidate           what bytes are in DDR          a score, for a
            PERMITTED?                  before the DMA; what bytes     candidate it was
            (whitelist, flush,          the fabric returns after       ARMED for
            ECC, manifest)              the DMA — both as raw
                                        words, hashed on the host
 may not    touch the board             judge permission              arm itself; report
            (host-only; pure)           (it carries no whitelist)     a match bit as
                                                                      evidence
 trusts     nothing from the board      identity + epoch of the       an explicit ARM
                                        session it runs in            write, and its own
                                                                      fault/recovery state
```

**Authority is per party and per control plane** (`zynq-psmap/docs/authority_requirements.md`):

1. **Host gate.** Pure function of the serialized bytes and the pinned manifest. It is the
   only party that says *permitted*. Its verdict is data (`gate_verdict`), never a flag.
2. **PS oracle.** The session that holds identity + epoch (`BoardSession`) and the two
   pinned instruments: the write plan (bytes staged in DDR → PCAP) and the read plan
   (PCAP → DDR → `md.l`). It witnesses link 2 by **reading back the staged DDR buffer
   before the write DMA is queued** (the same `md.l` path, the same re-read policy) and
   link 3 by the pinned PCAP readback after it. Both hashes are computed **on the host from
   words it received**. The oracle never judges permission and never arms anything.
3. **PL scorer.** Reused from the carrier: a fixed vector source, six LUT outputs, a target
   word, per-LUT match counters, `recovery_required` and a fault code. It scores only after
   an **explicit ARM write** and only while `¬recovery_required`. **It no longer owns
   `configuration_valid`** (§3) and **it has no ICAPE2 writer** — the PL never writes
   configuration in P3. It exposes a **heartbeat/eval counter** (§6 L2) so that "still
   computing" is observable.

## 3. `configuration_valid` — enforced in the PL, bound to the gate by a signed ARM (v0.2)

**History.** v0.1 made `configuration_valid` a host-computed predicate; the L0 review
rejected it as a bypass, because the PL never consumed it and a runner could ARM around it
(`l0_review_result.md`). Option A (a PL functional truth-table witness) closed
"fabric == what the host claimed" but not "== what the gate approved"; the owner rejected
it as it stood and conditionally accepted Option A′ as the basis of this rewrite
(`p3_enforcement_proposal.md`). What follows is A′ with the owner's six conditions
written in as **architecture requirements**, not notes.

### 3a. The property the hardware enforces

> **`score ⇒ valid MAC_K(candidate_commit ‖ expected_tables ‖ nonce)
>        ∧ functional_readout(six target LUTs) == expected_tables
>        ∧ ¬recovery_required ∧ fault == 0`**,
>
> latched by the PL as `configuration_valid_hw`, **the only condition on which the scorer
> arms.** There is no other ARM path.

Because `K` is held only by the gate signer (§3c), a valid MAC exists only for a candidate
the gate approved; because the fabric's behaviour is checked against the signed table, the
score is bound to the candidate actually in the fabric. Hence
`score ⇒ gate-approved candidate == actual LUT behaviour` — with the trust assumption
confined to key custody (§3c) and its limits stated (§3f).

### 3b. The ARM transaction, in order

1. **Nonce.** The PL exposes a 64-bit `nonce` at a pinned read-only AXI word. It is
   consumed once: the PL latches it at the first ARM verification of the session and
   refuses any later ARM that presents it again (`F_ARM_REPLAY`). A new session load yields
   a new nonce. The nonce is evidence, not a secret.
2. **Gate signer.** On `gate_verdict.writable`, the gate signer — a separate principal from
   the runner (§3c) — derives `expected_tables` (six 64-bit truth tables, `lut_truth_table`
   contract) from the candidate's INIT bits through the certified map, and computes
   `tag = MAC_K(candidate_commit ‖ expected_tables ‖ nonce)`.
   `candidate_commit` is the **full 256-bit `candidate_sha256`** (eight words); a truncated
   commitment is not used (owner condition; a 64-bit truncation's collision bound would
   otherwise have to be argued and recorded).
3. **ARM payload** = `candidate_commit` (8 words) ‖ `expected_tables` (12 words) ‖ `tag`
   (4 words for a 128-bit tag; the MAC is `arm_mac` contract) — 24 AXI writes into
   write-only staging registers, then one `ARM` strobe. The runner may write these; it
   cannot produce `tag`.
4. **PL verification, before anything else:** recompute the MAC over the staged payload and
   its own latched nonce. Mismatch → `fault = F_ARM_AUTH`, no sweep, no score, `recovery_required`
   set (a failed ARM is a fault of the same standing as a stream fault: only a reset clears
   it). Match → proceed.
5. **Functional sweep.** The PL drives all 64 input vectors of each target LUT and captures
   the outputs as `functional_readout`; compares with `expected_tables` in hardware.
6. **Latch.** `configuration_valid_hw ⟺ tag_ok ∧ readout == expected ∧ ¬recovery_required ∧
   fault == 0`. The scorer arms on it and on nothing else.
7. **Evidence, read-only:** the PL exposes the `candidate_commit` it armed for and the
   `functional_readout`. The host's run-log validator checks that the exposed commit equals
   the gate-approved `candidate_sha256` and that the readout equals the gate's expected
   tables — **evidence consistency, which does not replace the PL MAC gate** (owner
   condition).

### 3c. Key custody and provisioning — an architecture requirement, not a note

- **Principals.** `gate-signer` and `runner` are **different OS users** on the host. The
  runner never holds `K`; the gate signer holds it and signs only after its own whitelist
  verdict. The reviewer (owner) may be a third principal that provisions `K`.
- **Provisioning.** `K` (128 bits) is generated by the owner from a CSPRNG at L1 build
  time, embedded in the carrier bitstream as a constant that drives only the MAC core
  (no AXI path reads it; the L1 testbench and OOC netlist review must show no readable
  path), and written to `gate-signer`'s key file with mode `0400` owned by `gate-signer`.
  The bitstream's SHA-256 in `carrier_manifest` therefore pins which key the fabric holds.
- **Rotation.** A new key = a new carrier build = a new `carrier_manifest`; an old signed
  ARM is invalid against a new carrier by construction.
- **Failure behaviour.** Key file unreadable or absent → the gate signer refuses to sign
  (no ARM is produced; the runner stops at "no signed ARM", a refusal, not a stop about
  the die). Wrong key (stale file after rotation) → the PL answers `F_ARM_AUTH`; the run
  stops; the fault is attributable to custody, and the run log records the
  `carrier_manifest` sha the signer thought it was signing for.
- **Non-readability checks.** L1 exit: `K` does not appear in any readable register or in
  the readback path (the target columns are read back in L3; the MAC core is placed outside
  them and the frames that hold it are not in any readable set — stated in the manifest).
  Host: a test run *as the runner user* must fail to open the key file and must fail to
  produce a tag the PL (model) accepts.

### 3d. The MAC

`arm_mac` 1.0.0: **SipHash-2-4** with a 128-bit key over the 20 payload words plus the
8-byte nonce, output extended to 128 bits (two SipHash-2-4 evaluations with domain
separation, or SipHash-128) so the tag is 4 words. Threat model: a runner bypassing
process on the same host — not a cryptanalyst with the key. Published test vectors are
the conformance fixture for both the Python signer and the RTL verifier.

### 3e. What is enforced where

| link | property | enforced by |
|---|---|---|
| 1 | candidate is permitted (whitelist, flush verbatim, ECC) | host gate (pure) — unchanged from the carrier's §3b |
| binding | only a permitted candidate can be ARMed | **PL MAC gate**, key held by the gate signer |
| 2 | bytes staged in DDR == candidate | PS oracle (`md.l` of the full staged stream **and** of the candidate frames, hashed separately — neither substitutes for the other) |
| 3 | bytes in the fabric == candidate (non-LUT bits) | PS oracle PCAP readback |
| 3′ | the six LUTs behave as the signed table | **PL functional sweep** |
| evidence | hardware-exposed commit == gate-approved hash; readout == expected | run-log validator (second check, never the gate) |

### 3f. What this does not claim

- A host where the gate signer's principal, or root, is compromised is **outside the
  threat model**; this is not an absolute-security claim, it is the carrier's original
  "link 1 is the host's" assumption narrowed to one key file under one user.
- The hardware witnesses the six target LUTs' behaviour, not flush frames or non-target
  bits; those remain the PS oracle's and the gate's (rows 2–3 above).
- A routing corruption that does not reach a LUT input is not seen by the sweep.

## 4. Identity and epoch

Unchanged from `zynq-psmap`: one `BoardSession`, identity (`boardid`, `role`, `PSS_IDCODE`)
verified **before** the setup load on the session that performs it, one epoch, every reply
guarded (banner, prompt, prompt-mode), any disruption ends the epoch and clears the
identity, a `linux` control plane refused unconditionally, and — added by P3 — **the
oracle's two observations and the ARM must share the epoch of the gate verdict they
serve.** An oracle record whose epoch differs from its gate verdict's epoch is refused by
the validator, not merely flagged.

**Control plane for the ladder's board stages (L2–L4): U-Boot only.** This satisfies
`zynq-fabricmap`'s preregistration boundary as written ("if round 1 keeps a U-Boot-only
control plane, there is no gap") — a consequence worth noting: P3's instrument, driven from
U-Boot, is admissible under the existing Claim B preregistration without amending it.

**D1 — where the *loop* runs — is decided in `docs/decisions.md`, not here.** The ladder's
first board stages do not run a loop; they run one gated candidate per session under
U-Boot. D1 becomes load-bearing at L5.

## 5. Contracts

`docs/contracts.md`: every artifact that crosses a party or a repository boundary has a
`schema`, a `schema_version`, the compatibility policy (MAJOR incompatible / MINOR additive;
reject a foreign MAJOR, ignore unknown MINOR fields), a standalone validator, and a
conformance fixture. Initial set: `carrier_manifest`, `candidate`, `gate_verdict`,
`oracle_record`, `arm_record`, `score_record`, `run_log`, plus the imported
`zynq-psmap/pcap_probe_plan/1`, `zynq-psmap/pcap_write_plan/1`,
`zynq-psmap/stage_record/1`, `zynq-psmap/write_record/1`.

## 6. Acceptance ladder — every rung has PASS / HOLD / KILL, nothing skips a rung

| rung | what | PASS | HOLD | KILL |
|---|---|---|---|---|
| **L0** host-only architecture (this document, contracts, decisions) | **independent, non-author** review returns verdicts on the four questions in `decisions.md`; contracts have validators + fixtures; every imported artifact has a manifest row with sha256 and source commit | all four ruled and the validators/fixtures exist | a reviewer finds the predicate in §3 can be satisfied without an instrument observing bytes | a reviewer shows §3 is a bypass of the carrier's interlock rather than a re-establishment |
| **L1** the P3 carrier, host-side | a Vivado build (separate authorisation) of: the reused scorer, a heartbeat/eval counter, the pinned AXI window, **no ICAPE2**, the same isolated target columns, **the §3 MAC verifier, nonce, ARM staging registers, functional sweep and comparators**, frame table re-derived; OOC gate; `carrier_manifest` published | OOC clean; frame table digest reproduced; target columns blank in the base; **testbench negatives — wrong tag, replayed nonce, wrong commit, right tag with wrong table, unsigned ARM — none raise `armed`; no readable path to `K`**; L3's known answer pinned | resource/timing does not close | the design needs an ICAP writer, or `K` is reachable |
| **L2 = P2b** counter-class non-perturbation (first board stage, own ruling) | P2's protocol on the P3 carrier with **two** invariants: the eight stable-state words equal the baseline (P2's rule, unchanged) **and** the one heartbeat word advances within a pinned envelope with **both** bounds (`carrier_manifest.axi.heartbeat`), during ten PCAP reads and one write, against a matched no-read control | both invariants held, control stable | control unstable (either observable non-discriminating) | attributable violation: PCAP activity stalls, perturbs or runs away the computing design |
| **L3** one gated candidate, end-to-end (own ruling) | host gate → signer → stage → oracle link 2 → PCAP write → oracle link 3 → signed ARM → PL MAC + sweep → `configuration_valid_hw` → score; known-answer candidate (fabricmap's LUT0, pinned at L1 exit); **on-board negative controls: unsigned ARM, replayed ARM, ARM signed for another candidate — each must yield `F_ARM_AUTH`/`F_ARM_REPLAY` and no score** | positive case scores as predicted; every negative control refused; hardware-exposed commit == gate hash; run log replays | any hash unequal (a stop that says which link) | a score obtained without `configuration_valid_hw`, or a negative control that scores — the interlock did not hold |
| **L4** fault, restore, baseline (own ruling) | a deliberately illegal candidate refused by the gate (never sent); a legal candidate with a corrupted staged buffer refused at link 2 (never DMA'd); restore to base and baseline score after a stop | every refusal at the named link; restore verified by oracle link 3 | recovery requires power-cycle | a refused candidate reaches the fabric |
| **L5** the loop (D1 live) | N candidates in one session/epoch without a host in the decision loop, per `zynq-ehw` Claim M1's runtime properties | — | — | — (specified after L4; not before) |

Rulings are per rung, whole-of-rung, consumed by any outcome — the `zynq-psmap` model.

## 7. Kill criteria that apply to the whole line

- A score is ever recorded whose `oracle_record` does not carry two equal hashes in the
  same epoch as its `gate_verdict` — the interlock has been bypassed; the line stops.
- Any stage needs a routing-class bit, an ICAP writer, or a startup transition
  (SHUTDOWN/START/GRESTORE/JSTART) inside a probe — outside the scope this line is allowed
  (`zynq-autoehw` M2 prework §5 safety split; `zynq-psmap` §5c).
- The console link's fault rate makes rulings unwinnable (two of three P2 rulings were lost
  to it): fix the link (usbipd/port/cable) and prove it with an authorised soak before the
  next ruling — not by relaxing a guard.
- "Works only on Linux" — refused until D1 is decided and a Linux-side identity gate
  exists (`authority_requirements.md`).

## 8. What this repository will not do

Modify `zynq-psmap` or `zynq-fabricmap` (artifacts are imported, never edited in place;
findings flow back as **pointers**, as psmap did to fabricmap). Run Claim B (§9). Write
routing bits. Use ICAPE2. Boot Linux. Create a ruling. Touch a board before L2's ruling.

## 9. Relationship to Claim B and to `zynq-fabricmap`

P3 delivers the oracle and the interlock; `zynq-fabricmap` owns the Claim B
preregistration, arms, budget and score. When L3 passes, the fabricmap programme has what
its §7 asked for, and the decision to resume it — under its own preregistration, with the
P3 instrument as its `carrier` — is fabricmap's owner ruling, recorded there. P3 does not
pre-empt it.
