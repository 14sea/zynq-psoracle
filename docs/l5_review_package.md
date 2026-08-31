# L5 post-build review package — RESUBMITTED 2026-08-31 (round 3)

> **Read this first.** The sections below are the round-2 package and are **historical**.
> The canonical status table is `docs/status.md`.

## Round 3: what changed since the package you passed

The round-2 package passed and authorised push + rulings + board contact. Before acting on
that authorisation I checked its last step and found it had no executable; that search then
surfaced a defect in the pinned image itself. Five findings, evidence and fix are in
**`docs/l5_wire_findings.md`** — read that as the round-3 package. In short: the C
application's framed output had never been checked against the host validator that consumes
it (the rehearsal exercised the *Python* reference loop), so the image could not have
produced a session the host could adjudicate.

**Image `7540239f…` is WITHDRAWN. The pinned image is `b279459c…`** (byte-identical across
clean rebuilds; `build.sh` now emits the `.bin` itself).

What to review, in order:

| # | artefact | what it is |
|---|---|---|
| 1 | `docs/l5_wire_findings.md` | the findings, the fix, the honest limitations (§2 audit, §3 fclk0, §6 what this does NOT establish) |
| 2 | `firmware/p3_wire.{c,h}` | the serialisation as a pure unit |
| 3 | `tests/test_firmware_wire_contract.py` | the C bytes judged by the REAL validator, with two discrimination tests |
| 4 | `firmware/p3_app.c` | IDENT / HB / AUDIT / CLOSE; records with `seq`/`verified`/nested `evidence`; HW witness read not echoed |
| 5 | `host/l5_runner.py` + `tests/test_l5_runner.py` | the board runner that did not exist |
| 6 | `manifests/l5_manifest.json` | new `app_image_sha256`, `withdrawn_images`, BSP inputs |
| 7 | `docs/l5_prereg.md` §7 | the image change on record; the board procedure is unchanged |

**Unchanged by this batch:** the session's brackets, N = 8, the audit-all policy, the
PASS/HOLD/KILL conditions, the stop-loss, and the blocking `CPU_CLK_CTRL` preflight.

**Standing:** 366 tests / 0 skipped, fail-closed report in `evidence/tests/`; post-build
evidence in `evidence/l5_build/`. Nothing pushed, no `P3-L5`/`P3-K` ruling, no board contact.
**The firmware has still never run on hardware** — every green result here is host-side.

---

# L5 batch review package (D5 step 2) — everything host-only is done; the board is next

> **What this asks for.** Under `decisions.md` **D5**, host-only work runs continuously and
> one package is submitted before any board stage. This is that package. It asks the owner
> for **one** decision covering: the L5 firmware build (with a toolchain choice), the two
> rulings, and the first bounded board session as `docs/l5_prereg.md` fixes it. Nothing in
> this batch touched a board, created a ruling, or pushed a commit.

## 1. What was built in this batch

| artifact | what it is | how it is checked |
|---|---|---|
| `host/p3_genome.py` | the 292-bit genome codec and the single `derive` function (base → whitelist bits → word-50 ECC) | known-answer and blank round-trip **bit for bit**; every derived candidate passes the real gate; derive touches only whitelisted bits and word 50 |
| `fixtures/d1_corpus_v1.json` | the pinned conformance corpus, **N = 256** (review #2's Q7 condition) | regenerable; the suite spot-checks six indices against an independent regeneration and the whole file against the C twin |
| `firmware/p3_derive.[ch]` | the pure half of the application: sha256, CRC-32, frame ECC, genome codec, derive, stream build **and parse**, both hash domains, the pinned readback + cleanup command streams, base64url both ways, the nonce model, the identity page | compiled with the host compiler and driven over **all 256 corpus entries**: both hashes match Python exactly; build→parse round-trips; readback/cleanup streams equal `zynq-psmap`'s; ECC equals the imported prjxray port; CRC/base64/nonce/page all match |
| `firmware/p3_app.c` | the board half: HAL + state machine, mirroring `host/l5_refloop.py` | **never compiled** (§4); source audit of the properties the interlock depends on |
| `firmware/p3_search.c` | the reference sampler behind §4.1's interface | deterministic; the search itself is explicitly out of D1's scope |
| `host/l5_notary.py` | T1 framing (full 128-bit token, CRC, drop budget), the relay + `notary_log`, the collector + §3c classification | 20 protocol tests incl. seq gaps, foreign tokens, CRC budget, banner-vs-terminal precedence |
| `host/l5_refloop.py` | the reference state machine the firmware mirrors | end-to-end rehearsal against a fake standalone PL through the **real** relay and **real** signer |
| `validators/records.py` | eight standalone schemas + `validate_standalone_run_log` rules (vii)–(ix) | every rule has its own negative test asserting on the rule tag |
| `manifests/l5_manifest.json`, `docs/l5_design.md`, `docs/l5_prereg.md` | the pinned quantities, the design record, the preregistration | — |

**Test suite: 340 tests, all passing** (`host/run_tests.sh`, fail-closed evidence report).

## 2. What is proven, and by what

- **The application's arithmetic is the specification's arithmetic.** Not "reviewed to be
  the same" — *executed* and compared over 256 candidates covering the whole whitelist,
  including the two that matter operationally (the blank base and fabricmap's known answer).
  If the C and the Python ever disagree by one bit, the corpus test fails host-side rather
  than a board session failing at link 2.
- **The state machine's refusals are exercised**, on the Python side, against a fake PL that
  verifies MACs with the real signer's key: link-2 corruption stops before any DMA; a fabric
  tamper is caught; a wrong nonce echo refuses the whole loop; a gate refusal is survived;
  the closing unsigned ARM is refused and is genuinely the last device operation (the fake's
  fault is sticky, as the RTL's is).
- **The firmware cannot reach the key.** No firmware source names `0x2160‥216C`; the
  AXI write allowlist ends exactly where the key window begins; every PL access goes through
  one checked accessor; the four DMA transactions are the only ones declared or issued; no
  SLCR write exists (the one SLCR symbol is the IDCODE, read once); no cache maintenance
  call exists, because the MMU attribute is the fix.

## 3. The known gap, stated plainly

**`firmware/p3_app.c` has never been compiled.** There is no ARM bare-metal toolchain on
this host, and compiling it is part of the build authorisation, not of this batch. Its
first compile will find whatever a first compile finds. Two things bound that risk, and
neither removes it:

1. Everything that could be moved out of it was moved into `p3_derive.c`, which **is**
   compiled and executed against the reference — including every hash the interlock depends
   on and both command-stream builders.
2. The properties an audit can check without executing are checked (§2, third bullet), and
   they are the safety-relevant ones.

What remains unchecked in it is ordinary firmware risk: types, BSP API signatures, buffer
sizes, and whether the UART framing behaves under real timing. The first board session is
preregistered as a **bounded** one (N = 8) partly for that reason.

## 4. Decisions requested — the reviewer's items

| # | item | author's position |
|---|---|---|
| D-a | **Toolchain**: xPack `arm-none-eabi-gcc` (pinned tarball, no system install), distro `gcc-arm-none-eabi`, or a Vitis install | **xPack**, version pinned into `manifests/l5_manifest.json` with its sha256; download forced over IPv4 (this box's IPv6 is broken) |
| D-b | **XDcfg deviation**: spec §1 names the `XDcfg` driver; the application instead issues the four pinned DMA tuples with direct register writes in psmap's exact order | Accept the deviation: the tuples *are* the contract, and direct writes are what the audit can check tuple-for-tuple. If the reviewer prefers the driver, the loop changes but the tuples do not |
| D-c | **Watchdog period** (`P3_WDT_LOAD`, deliberately 0 in the source) | Pin at 3 × heartbeat = 30 s, computed from the private-timer clock at build and recorded in the manifest |
| D-d | **Console UART**: the BSP's stdout must be the UART U-Boot uses on `17A6` | Confirm at build from the BSP configuration; refuse to guess it here |
| D-e | **First session's audit rate**: the prereg fixes **every candidate** audited (not the long-run 1/16) | Confirm — it discharges the self-report caveat completely for session 1 |
| D-f | **N = 8** candidates for the first session | Confirm; a long run is a separate prereg and ruling |

## 5. If this package passes, the sequence is

1. Toolchain installed and pinned; `p3_app.c` + `p3_derive.c` + `p3_search.c` compiled;
   `manifests/l5_manifest.json` completed (`app_image_sha256`, toolchain, watchdog, UART).
2. Any compile-driven change to `p3_derive.c` re-runs the 256-entry corpus test **before**
   anything else — a change there that the corpus does not cover is not a change that ships.
3. Owner creates `whole-of-probe P3-L5` and `provisioning P3-K`.
4. Power cycle → boundary verifier as the runner → the session of `docs/l5_prereg.md` §4,
   run in the background, no shell timeout, waited on by pid.
5. `docs/l5_findings.md` with the adjudication, and `docs/status.md` updated.

## 6. Boundaries observed in this batch

No board contact. No ruling created or claimed. No firmware built. No push — the repository
is **4 commits ahead of `origin/main`** (`89916cf`, `89d0473`, `4841917`, and this batch),
pending the owner's decision on pushing them together with the ratification of `90566b4`.
`zynq-psmap` and `zynq-fabricmap` were not modified (`git status` clean in both).
