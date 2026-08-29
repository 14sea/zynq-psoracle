# Whole-line gate review package — before any P3 ruling

Prepared 2026-08-29 under the owner's mandate ("到「建立 whole-of-probe ruling／實際送板上
byte」前，再做一次整體 gate review；未取得該 ruling 前仍不得碰板"). This is the package for
the non-author reviewer(s); nothing here is self-certified. HEAD at preparation: see `git log`.

## What is being asked

Rule on whether the line may request its **first board ruling**, and which: the ladder
says L2 (P2b) is the first board stage, then L3 (three rulings for the negative controls).

## What exists (all host-only, 198 tests, `python3 -m unittest discover -s tests`)

| item | where | evidence |
|---|---|---|
| L0 architecture §3 v0.2 (PL-enforced, gate-signed ARM) | `docs/p3_architecture.md`, `docs/l0_review_result.md` | accepted as basis by the owner; L0 **not marked PASS** (non-author exit review outstanding) |
| L0 exit deliverables | `validators/`, `docs/import_manifest.md`, `tests/` | schema policy, run-log rules (i)–(vi), signer/principal model, two-way import closure |
| L1 P3 carrier | `rtl/`, `tb/`, `sim/run_all.sh`, `docs/l1_design.md` | fixture bench: every negative never arms; Vivado dummy-key build +7.8 ns, keyed build +6.9 ns, isolation 6/0, ICAPE2 0, 12 target FARs blank; `builds/dummy_key/`, `manifests/keyed_b4c022a2.json` |
| link 1 gate | `host/p3_gate.py`, `tests/test_p3_gate.py` | fabricmap rules verbatim; known answer writable; 11 refusals by kind |
| host oracle | `host/p3_oracle.py`, `tests/test_p3_oracle.py` | pinned to fabricmap's published silicon scores |
| L2 tooling | `host/l2_runner.py`, `host/l2_heartbeat.py`, `docs/l2_spec.md` | fake-clock tests: PASS / STALLED STOP / HOLD-at-control |
| L3 tooling | `host/l3_runner.py`, `host/sign_arm.py`, `docs/l3_design.md` | fake board: PASS, link-2/3 stops before DMA/ARM, PL refusals, negative controls, KILL on a validating control |

## Questions the reviewer must answer (each PASS / HOLD / KILL)

1. **L0 exit**: do the validators and fixtures make the contracts testable as written, and
   is the import manifest closed both ways? (`docs/import_manifest.md`, `tests/`)
2. **L1 exit**: is there any readable path to `K` (register map `rtl/p3_axil.v`; MAC core
   placement outside the target columns; D4 bitstream residual)? Are the bench negatives the
   ladder's five? Is the frame-table/manifest derivation acceptable?
3. **Link 1 transfer**: is reusing fabricmap's frame rules verbatim over a *different
   transport* (PCAP envelope streams, 505-word FDRI, flush frame = next device-order frame)
   sound? Specifically: the flush frame written by auto-increment is pinned base content —
   does the reviewer accept that as equivalent to the carrier's ICAP envelope? (`host/p3_gate.py`,
   `tests/test_p3_gate.py`)
4. **Link 2/3 domains**: `staged_sha256` (frames) vs `staged_stream_sha256` (stream) vs
   `readback_sha256`; rule (iv). Is anything host-computed being treated as authority?
5. **ARM path**: nonce LE bytes, tag word packing, commit words — all fixture-verified
   against the RTL; does the reviewer accept the fixture as the binding between
   `validators/signer.py` and `rtl/p3_siphash.v`?
6. **Negative controls**: one per session because faults are sticky — accept three rulings,
   or require an RTL change (non-sticky auth fault)? The sticky design is deliberate
   (no retry-guessing against the MAC).
7. **L2 envelope**: derived bounds (J = 50 ms, T = 2 %) — acceptable as a pre-registered
   envelope, with measured bounds pinned into the manifest after L2?
8. **Kill criteria** (`p3_architecture.md` §7) — any already triggered?

## What is explicitly NOT claimed

No board contact has occurred for P3. No rung is PASS. The fakes prove runner sequencing
and refusals only. The PL is proven only in simulation and by build reports. Sibling
repositories are unchanged. No remote exists.

## Re-review delta (2026-08-29, after HOLD → owner chose D4 option A)

What changed since the HOLD (`docs/whole_line_gate_review_result.md`):

1. **Key no longer in the bitstream** — write-once/write-only key register, `key_loaded`,
   `F_ARM_NOKEY`; SipHash key is an input; public build `builds/p3/` (+7.58 ns, isolation
   6/0, ICAPE2 0); keyed artifacts withdrawn. Bench: unprovisioned → 12, wrong key → 13,
   read/rewrite → SLVERR, reset clears. (`docs/l1_design.md` change log.)
2. **Real OS principal, established and verified**: `p3signer` / `p3jtag`, key store
   `/var/lib/p3signer/keys` (K moved, runner copy shredded), pod udev-owned by `p3jtag`,
   one sudoers line. `host/verify_principal_boundary.py` run **as the runner, pod
   attached**: R1–R5 ALL PASSED — `evidence/boundary/principal_boundary_2026-08-29.json`.
   The L3 runner refuses to start without a validated, all-passed, < 6 h record.
3. **Signer path exercised live through the real principal** (host-only): sign OK,
   unwritable verdict refused, provisioning prepare writes nothing, execute without the
   `provisioning P3-K` ruling refused cleanly.
4. **F2 stated as a limitation** (`p3_architecture.md` §3f): a console holder can replace
   the PL; A does not address it; excluded by the threat model.
5. Pre-positive negative controls `unprovisioned` / `wrong_key` in runner + fake; L3 now =
   five sessions (+ a `provisioning P3-K` ruling for each provisioned one).

Questions for the re-review: (a) is D4 discharged by 1–3; (b) is F2 accepted as a stated
limit; (c) is the DAP mem-AP provisioning path acceptable as a **separate ruling** before L3
(L2 needs no key); (d) the `provisioning P3-K` ruling model — one per provisioned session.
