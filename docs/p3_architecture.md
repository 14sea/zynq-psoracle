# P3 — re-establishing the write-integrity interlock around a PS-side oracle

> **HOST-SIDE ARCHITECTURE DRAFT. Nothing here is evidence, nothing here authorises a
> board action, a ruling, a Vivado build, or a change to `zynq-psmap` or `zynq-fabricmap`.**
> Owner authorisation of 2026-08-29 covers exactly: this repository's boundary, this
> document, the acceptance ladder, the three-party authority model, the definitions of
> `configuration_valid` / identity / epoch, the schema contracts, D1, and kill criteria.
> Everything else waits for cross-review and a separate ruling.

Status: draft v0.1, 2026-08-29. Author: Claude (host/gate side). Not reviewed.

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

## 3. `configuration_valid`, redefined — a host judgement over PS observations

In the carrier, `configuration_valid` was a **fabric** bit raised by the carrier's own
readback compare, and the host had no channel into it (`claimb_findings.md` §3.4.1). That
is what could not be closed. In P3:

> **`configuration_valid` is a host-computed predicate**, true iff, within one session and
> one epoch:
>
> `gate_verdict.writable`
> ∧ `sha256(staged_ddr_words) == candidate_sha256`     (link 2, PS oracle, before the DMA)
> ∧ `write DMA completed with no error bit`
> ∧ `sha256(pcap_readback_words) == candidate_sha256`   (link 3, PS oracle, after the DMA)
> ∧ `¬recovery_required ∧ fault == 0`                  (PL, read over the pinned AXI words)
>
> **and only then may the host issue ARM.**

Three things make this a *re-establishment* and not the "dressed-up bypass" §3.4 forbids:

- every link is checked by an instrument that **observed the actual bytes** — the host gate
  parsed them, the oracle read them out of DDR and out of the fabric;
- the PL still refuses to score without ARM and still carries its own fault/recovery
  state, so a host that skips the predicate cannot obtain a score *silently*: the run log
  records the predicate's inputs (all three hashes, the DMA status, the AXI words) with the
  ARM, and a consumer re-derives it (`docs/contracts.md`, `oracle_record`);
- the PL reports **no match bit**. There is nothing on the fabric side to be taken on
  trust, because there is nothing on the fabric side that claims to verify.

What is *lost* relative to the carrier: the fabric no longer verifies itself. What is
*gained*: the verification is done by an instrument that has actually returned non-blank
content on this die, twice under independent confirmation. The trade is stated, not hidden.

**Candidate hash domain.** `candidate_sha256` is over the FAR-ordered canonical frame set
(the carrier's `run_log` domain), computed by the host gate from the bytes it accepted;
the oracle's two hashes are over the same frames extracted from the staged stream and from
the readback buffer respectively. The three are comparable because they are the same
domain; the *stream* hash (`sequence_sha256`) is kept separately to pin what was sent.

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
| **L1** the P3 carrier, host-side | a Vivado build (separate authorisation) of: the reused scorer, a heartbeat/eval counter, the pinned AXI window, **no ICAPE2**, the same isolated target columns, identity of the frame table re-derived; OOC gate; `carrier_manifest` published | OOC clean, frame table digest reproduced, target columns blank in the base | resource/timing does not close | the design needs an ICAP writer to function |
| **L2 = P2b** counter-class non-perturbation (first board stage, own ruling) | P2's protocol on the P3 carrier with **two** invariants: the eight stable-state words equal the baseline (P2's rule, unchanged) **and** the one heartbeat word advances within a pinned envelope with **both** bounds (`carrier_manifest.axi.heartbeat`), during ten PCAP reads and one write, against a matched no-read control | both invariants held, control stable | control unstable (either observable non-discriminating) | attributable violation: PCAP activity stalls, perturbs or runs away the computing design |
| **L3** one gated candidate, end-to-end (own ruling) | host gate → stage → oracle link 2 → PCAP write → oracle link 3 → `configuration_valid` → ARM → score; known-answer candidate (fabricmap's `known_answer.json` LUT0) | score equals the host oracle's prediction; all three hashes equal; run log replays | any hash unequal (a stop that says which link) | a score obtained with `configuration_valid` false — the interlock did not hold |
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
