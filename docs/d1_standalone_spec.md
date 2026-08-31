# D1 — the standalone loop: host-only specification (v0.2, 2026-08-31 — revised after review #1 HOLD, **not re-reviewed**)

> **Status note:** this document specifies; it authorises nothing. It was written under the
> owner's authorisation of 2026-08-31 — *D1 host-only specification only: no L5 build, no board
> contact, no ruling.* The canonical status is `docs/status.md`. Everything below is the
> author's proposal until a non-author review returns verdicts on the questions in §10.
> Review #1 (2026-08-31) returned **HOLD** with four blockers, recorded verbatim in
> `docs/d1_review_result.md`; v0.2 addresses all of them and the four secondary items
> (§12 change log) and awaits re-review.

## 0. What this document is, and what it is not

`docs/decisions.md` D1 recorded, under the owner's continuous host-side mandate of 2026-08-29,
the *working decision* that the L5 loop runs **standalone** (a bare-metal application on the
Cortex-A9, started from the U-Boot session, never returning to it), and promised that "L5's
specification will carry the `app_identity` contract". L0–L4 have since passed on `17A6`
(`docs/status.md`), all of them under the U-Boot control plane, with one gated candidate per
session. This document makes the standalone decision concrete enough to be reviewed: what the
control plane is, how identity and epoch are re-established on the far side of `go`, where each
of the three parties of `p3_architecture.md` §2 lives when the loop is on the board, what the
per-candidate transaction is, what evidence the loop leaves, and what of `zynq-ehw` Claim M1's
runtime properties transfers and what does not.

It does **not**: change the carrier (`builds/p3/p3.bit`, `956379fa…` — no RTL change is part of
D1), change D4 (same signer principal, same key store, same JTAG provisioning), specify the
search algorithm, authorise an L5 build, name a toolchain as chosen, or create a ruling text.
§11 lists what would come next and states that none of it is authorised by this document.

One consequence of the 2026-08-29 decision was not stated then and is stated here first,
because everything else depends on it: **the standalone loop moves the search and the PS
oracle onto the board; it does not move the gate or the key.** `p3_architecture.md` §2 makes
the host gate "the only party that says *permitted*", and §3c makes `K` the property of a host
OS principal that the runner cannot read. A loop in which the application both chose
candidates and held `K` would be the single-principal arrangement the whole-line gate review
rejected for D4 (`docs/whole_line_gate_review_result.md`), on the board instead of on the host.
Under this specification the host therefore remains **a notary** — it re-derives the whitelist
verdict and signs — and is not in the *search* loop: it never proposes, ranks, scores, or
recovers a candidate while the run is in progress. Whether that is an acceptable reading of
"no host in the decision loop" is the first question for the reviewer (§10 Q1), not something
this document decides.

## 1. The `standalone` control plane

| | `uboot` (L2–L4, unchanged) | `standalone` (L5, this document) | `linux` |
|---|---|---|---|
| who executes device operations | U-Boot, one command at a time from the host session | the application, autonomously, from DDR | refused (`decisions.md` kill criterion 4; `authority_requirements.md`) |
| how it starts | power-on → TF-card U-Boot → `BoardSession` | from the U-Boot session: identity verified → setup load (carrier) → key provisioned (signer, JTAG) → **application image loaded into DDR by the same sha-gated ymodem path as the setup load** → identity page written (§3) → `go <app_entry>` | — |
| how it ends | any disruption, or the runner's summary | **only by a reset** (the application never returns; the U-Boot prompt never comes back inside the epoch). A reset is observed by the host as a U-Boot banner and ends the standalone epoch | — |
| authority | `BoardSession` capabilities, one epoch | `app_identity` (§3): re-established by the application from what it can itself observe, bound to the host's U-Boot-epoch identity by a token written before `go`. **Crossing from `uboot` to `standalone` invalidates the U-Boot authority unconditionally** (`authority_requirements.md`: authority is per control plane; a token is not an inheritance, it is one input to a fresh identity) | — |
| PL state across the crossing | — | `go` does not touch the PL. The application **must not** run `ps7_init`, write `FPGA_RST_CTRL`, the level shifters, or any FCLK/PLL register: the carrier, `key_loaded`, and the nonce survive `go` unchanged, and the application *verifies* that they did (§3) rather than re-creating them | — |

The application is built on the Xilinx standalone BSP with the `XDcfg` driver — the driver
whose source settled `zynq-psmap` §8a (the readback is two unidirectional DMA commands) and
which is present locally (`/home/test/Xilinx/2025.2/data/embeddedsw`: `devcfg_v3_9`,
`standalone_v9_4`). **No ARM bare-metal compiler is installed on this host** (`arm-none-eabi-gcc`
absent; Vitis not installed). That is an L5-build prerequisite, recorded here so the L5 design
does not discover it; it is not decided by this document.

## 2. The three parties when the loop is on the board

`p3_architecture.md` §2, with the *location* column added. Authority does not move; two
parties change where they execute.

| party | L2–L4 | L5 standalone | authority (unchanged) |
|---|---|---|---|
| host gate (link 1) + gate signer | host: `host/p3_gate.py`, `host/sign_arm.py` as `p3signer` | **host, as notary** (§5): the signer re-derives the canonical frames from the genome the application sends, runs fabricmap's rules verbatim, and signs `MAC_K(commit ‖ tables ‖ nonce)` only on `writable` | the only party that says *permitted*; the only holder of `K` |
| PS oracle (links 2, 3) | host: the runner observes DDR (`md.l`) and the fabric (PCAP readback) through the console and hashes on the host | **the application**: it stages, re-reads DDR, DMAs, reads the fabric back over PCAP, and hashes on the PS. **Its records are self-reports of the writer** (§4, §7); what compensates is the PL's own witness (3′), the post-run replay, and audit-on-request of raw words (§4.7) | never judges permission; never arms itself |
| PL scorer + ARM gate | unchanged | unchanged (no RTL change) | arms only on `configuration_valid_hw` |
| the search | none (one known-answer candidate) | **the application**: proposes, selects, keeps the champion, decides to continue or stop | none — a search has no authority; it *asks* |

**What is a downgrade and is declared as one.** L0's Q3 rejected a PS-computed hash for link 2
because "the host would be trusting a summary it did not observe". Under `standalone` the host
observes nothing during the run — that is the definition of the plane — so the question changes
from *who hashes* to *what the evidence is*. This specification does not pretend the application's
`staged_sha256` / `readback_sha256` have the standing of L3's host-observed ones: they get their
own schema (`app_oracle_record`, §7), the validator never accepts one where an `oracle_record`
is required, and the loop keeps the **raw words** it observed for audit (§4.7). For the six
target LUTs, link 3′ (the PL functional sweep against the signed tables) is unchanged and is
hardware; for flush frames and non-target bits there is, as in L3, no witness other than the
writer's own readback — in L3 that writer was the host runner, here it is the application.
Nothing in L5 is weaker on that point than L3 was; nothing is stronger either.

## 3. Identity and epoch — the `app_identity` contract

`zynq-psmap`'s identity is `boardid` + `role` (U-Boot environment) + `PSS_IDCODE` (SLCR),
verified on the U-Boot session before the setup load. Two of the three do not exist on the far
side of `go`: a bare-metal application has no `printenv`. The application therefore establishes
its own identity from what it *can* observe, and the host binds that identity to the one it
verified under U-Boot by a token it writes in the same U-Boot epoch.

### 3a. Before `go`, on the U-Boot session (host, `BoardSession`, one epoch)

1. `verify_identity()` — as today. 2. Setup load of the carrier, sha-gated, `plmark` — as
today. 3. Provisioning of `K` by the signer over the DAP mem-AP under a `provisioning P3-K`
ruling — as today; the host reads `STATUS` and requires `key_loaded = 1`. 4. Application
image: `loady` to a pinned DDR address disjoint from every buffer in §4.2, sha-gated exactly as
the setup load is (the image hash is in the L5 manifest; a mismatch is a session refusal, not a
warning). 5. `dcache off` (the existing `ensure_dcache_off`) — then the host writes the
**identity page** with `mw.l` and reads it back with `md.l`:

```
identity_page (24 words at IDENTITY_PAGE, 64-byte aligned, pinned in the L5 manifest)
  0      magic              0x50334944  ("P3ID")
  1      layout_version     2
  2..5   token              the FULL 128-bit session token, host-generated per session (os.urandom), never reused
  6      uboot_epoch        the BoardSession epoch in which words 2..5 were written
  7      app_image_sha_lo32 low 32 bits of the application image sha256 the host ymodem-verified (an identifier only; the authoritative hash is the host's, §3a step 4)
  8..15  carrier_sha256     the FULL 256-bit carrier bitstream sha256, big-endian word order (review #1 blocker 3: no truncated identity anywhere)
  16..17 nonce_seen         the PL nonce the host read on this session after provisioning (= NONCE_SEED unless an ARM has happened, which it has not)
  18     status_seen        the PL STATUS the host read then (must have key_loaded=1, alive=1, fault=0)
  19     seed               search seed (host-supplied test mode, §6) — recorded, never secret
  20     budget             candidate budget for this session (0 = until stop condition)
  21     flags              bit0 holdout_mode, bit1 watchdog_enabled (§6), others zero
  22     reserved           0
  23     checksum           xor of words 0..22
```

6. The host reads `NONCE_LO/HI` and `STATUS` one last time (they must equal words 16..18), records
everything above in the run log, and issues `go <app_entry>`. From that byte on the U-Boot
authority is void. The host's console role from here is **relay and collector** (§5): it
parses framed lines the application prints; it never sends a U-Boot command again in this epoch.

### 3b. At application start (the application, before any device operation)

The application establishes `app_identity` and refuses to run the loop unless **all** hold:

| check | source | why |
|---|---|---|
| `PSS_IDCODE & 0x0FFFFFFF == 0x03722093` | SLCR `0xF8000530` | the silicon the host verified (psmap's rule, same mask) |
| identity page valid | DDR (read through a non-cacheable mapping, §4.2): magic, schema, checksum | the host wrote it in this epoch |
| `STATUS` alive, reserved bits zero, `fault = 0`, `recovery_required = 0`, **`key_loaded = 1`** | AXI `0x2004` | the same provisioned carrier instance is still there; a reconfiguration between the host's last read and `go` would have cleared `key_loaded` |
| `NONCE == nonce_seen` | AXI `0x202C/0x2030` vs page words 16..17 | binds the application to the exact PL state the host last observed: the nonce steps on every ARM attempt and resets to the seed on reconfiguration |
| FCLK0 as pinned | decode the PLL and divisors from SLCR (the manifest's rule: "set and verified by decoding the PLLs, never by writing a remembered constant") | the L2 heartbeat envelope and the scorer's timing assume 50 MHz; **read-only** — the application never writes a clock register |
| DEVCFG sane | `INT_STS` error mask `0x00F4C840` clear, `CTRL` PCAP mode/PCFG_PROG as the write plan requires (P1's masks, unchanged) | the DMA path is in the state the pinned transactions assume |

The record it publishes (first framed line, §7):

```yaml
schema: app_identity
schema_version: "1.0.0"
control_plane: standalone
pss_idcode: <hex>
token: <hex128>                  # echoed from the page — the host refuses any request whose token differs
uboot_epoch: <n>                 # echoed
carrier_sha256: <hex256>         # echoed from the page, full width
nonce_at_start: <hex64>          # must equal identity_page.nonce_seen
status_at_start: <hex>           # must show key_loaded, alive, no fault
fclk0_hz_decoded: <n>
app_image_sha256: <hex>          # the application's own image hash over its text+rodata as linked (self-measurement; the host's ymodem sha is the authoritative one)
app_epoch: 0
findings: []                     # any non-empty list => the loop does not start; terminal record follows
```

**What the carrier check does and does not establish (review #1 blocker 3).** The
application cannot hash the fabric — no party can: PCAP readback returns frames, not the
bitstream file, and hashing every frame is not among the pinned operations. "The specified
carrier is loaded" is therefore established by a chain whose links are named: (1) the host
sha-gated the setup load against the manifest's **full** hash on this same session
(`BoardSession` refuses a mismatched image before any byte is sent); (2) the PL instance the
host then observed is the instance the application finds — the `key_loaded = 1` and nonce-echo
checks above, since a reconfiguration in between would have cleared both; (3) the full 256-bit
hash rides in the identity page and in every record, so the identity is collision-free *as an
identifier*. Links 1 and 2 are the verification; link 3 is bookkeeping. The page hash is not,
and is not claimed to be, an application-side measurement of the fabric.

### 3c. The application epoch

`app_epoch` is `0` for the life of the application; it is not a counter that advances, it is a
name for "this run since `go`". **How it ends is a four-kind taxonomy (review #1 blocker 1),
and every schema, validator, summary and the watchdog use exactly these names:**

| kind | causes | closing obligations (§4.0) | terminal evidence | host verdict |
|---|---|---|---|---|
| `COMPLETED` | the budget reached or the search's stop condition — both checked **before** a candidate is proposed, so a normal end never pre-empts the brackets | closing restore **and** closing baseline ARM **and** closing unsigned ARM — all three mandatory | `session_summary` framed line | PASS / HOLD per the run's own criteria |
| `STOPPED` | link 2 or link 3 mismatch (§4.4, §4.5); a DEVCFG error bit; an AXI precondition failure; a PL refusal of an ARM (§4.6 — the fault is sticky, no retry inside an epoch); the identity page changing under the application (re-read at every notary exchange) | closing restore (write + readback only) as a mandatory finally **whenever DEVCFG is healthy** — the restore is a write, not an ARM, so a sticky ARM fault does not excuse it; **no ARM of any kind** after a PL fault | ring dumped in full (§4.7), then the terminal line naming the STOP | HOLD, or KILL where the ladder says so |
| `PROTOCOL` | notary timeout; a malformed reply; CRC-dropped lines beyond the pinned drop budget (§5b); a token, `seq`, or nonce inconsistency in either direction | as `STOPPED` | as `STOPPED`, STOP name `PROTOCOL_*` | HOLD — never KILL: the transport is outside the interlock |
| `CRASHED` | the watchdog (§6a); any end the host *infers* rather than receives — a U-Boot banner, console silence past 3 heartbeat intervals | none — the application is gone | none from the application; §6a's post-mortem rules apply | CRASHED, `session_summary` written host-side |

**A gate refusal is not on this list.** `REFUSED_BY_GATE` (§4.3) is a per-candidate outcome:
recorded, counted, loop continues — an illegal genome is the search's business, not the
session's. On the notary path only the `PROTOCOL` row ends the epoch: the channel misbehaving,
never the gate saying no.

**A new epoch is a new session**: power cycle or reset → `BoardSession` → identity → setup load
→ provisioning → image → page → `go`. Whether an SLCR soft reset would preserve the PL
configuration is not settled by this line's evidence and does not need to be: L5 treats every
PS reset as requiring the full per-session bring-up, as L2–L4 already do.

The host collector (§5) ends the epoch on its side on any of: a U-Boot banner or prompt on the
console (`BOOT_BANNER_RE`, `PROMPT_ANY_RE` — the same regexes), a framed line whose token is not
this session's, a sequence gap, or console silence longer than the pinned heartbeat interval
× 3 (§6) — classified `CRASHED` unless a terminal line arrived first. After that it accepts
nothing further as evidence of this epoch.

## 4. The per-candidate transaction

L3's chain (`docs/l3_design.md` §1), with the observer moved onto the PS and the notary
round-trip inserted between link 1 and staging. **One candidate at a time; one outstanding
notary request at a time; every step STOPs the epoch on failure, never retries.**

### 4.0 Session brackets: the base candidate first and last

Every session begins and ends with the **blank candidate** (all twelve target frames = the
pinned base), signed like any other, whose ARM must yield `[18, 22, 20, 20, 20, 18]` (train;
L4's baseline, fabricmap's `base_restore`). The opening baseline is the session's positive
control (the fabric, the key, the notary and the scorer agree before any search); the closing
one is L4's *restore* (the fabric is left blank) with the same score as evidence that the
session did not drift. After the closing baseline the application performs **one unsigned ARM
attempt** (zero tag) — the negative control of the session, expected `F_ARM_AUTH`, which is
sticky and therefore correctly the *last* device operation of the epoch. A session whose
closing negative control validates or scores is a KILL, as in L3.

**Whether the brackets can be skipped is settled by §3c's taxonomy, not left to timing:** on
`COMPLETED` all three closing steps are mandatory (the budget/stop check runs before a
candidate is proposed, so a normal end always reaches them); on `STOPPED` / `PROTOCOL` the
restore write is a mandatory finally whenever DEVCFG is healthy, and no ARM follows; on
`CRASHED` nothing is promised. `session_summary` records each closing step as done or
`not_reached` with the kind (§7).

### 4.1 Propose (the search; out of this document's scope except for its interface)

The search produces `genome_i`: a **292-bit vector over the manifest's whitelisted addresses**
(`phenotype_manifest.ownership.whitelist_by_far`, 292 `(far, word, bit)` addresses), in
**canonical order = ascending `(far, word, bit)`**, packed little-endian into 10 words (bits
292..319 zero). A genome is not a set of frames; frames are *derived* from it by one
deterministic function that both sides implement (§4.2) and whose outputs the host pins
against a corpus before L5 (§11). The seed and the algorithm identifier are in the run log;
determinism given the seed and the observed scores is a requirement (M1 replay, §6).

### 4.2 Canonical frames, staging, and the cache rule

`frames = derive(base_frames, whitelist, genome)`: start from the twelve pinned base target
frames, set each whitelisted bit to the genome's value, recompute word 50's ECC with the
imported `frame_ecc` rule (13 bits, nothing else changes), and leave the three flush frames as
the base **verbatim**. The three envelope streams (534 words each: P1's shape, FDRI 505 words =
four targets + the flush frame the device's auto-increment reaches next) are built exactly as
`host/p3_gate.py` builds them. The C implementation of `derive`, the ECC, the stream builder and
the frame hash is **pinned to the Python by a host test over a corpus** (the known answer, the
blank candidate, and N random genomes): identical words, identical hashes, before any L5 build
is contemplated.

**Buffers.** The staging buffers (3 × 534 words), the readback command (43 words) and
destination (202 words) buffers, the identity page, and the evidence ring (§4.7) live in one DDR
region that the application maps **non-cacheable** (`Xil_SetTlbAttributes`, strongly-ordered or
device memory) before it touches them, with the attributes read back from the translation table
and recorded in `app_identity`. This closes by construction the bug class the L3 diagnostic
session found (`docs/l3_findings.md`: staging through the D-cache made the DMA read stale DDR
while `md.l` "confirmed" the cached copy). Per-operation cache maintenance
(`Xil_DCacheFlushRange` / `InvalidateRange`) is **not** the chosen mechanism: it is correct
when applied everywhere and silently wrong when one call is missed, and the diagnostic showed
what "missed once" looks like. Buffers are 64-byte aligned and never cross a 4 KiB boundary
(psmap §6 [N2]); addresses are pinned in the L5 manifest and are disjoint from the application
image and its stack/heap, with a host test over the linker map.

### 4.3 The notary round-trip (link 1 and the signature — host, §5)

The application reads `NONCE` (stable: it steps only on ARM attempts, and there is none
outstanding), then sends `sign_request {token, app_epoch, seq, genome, nonce}` and waits, bounded.
The signer (`p3signer`, via the relay) derives the same canonical frames, builds the same
streams, runs `host/p3_gate.py`'s gate (fabricmap's rules, verbatim) on them, and only on
`writable` computes `expected_tables` (`host/p3_oracle.py`), `commit = candidate_sha256`, and
`tag = MAC_K(commit ‖ tables ‖ nonce)`. Reply: `sign_reply {seq, commit, tables[6], tag}` or
`refused {seq, finding_kinds}`. A refusal is **not** an error of the loop — an illegal genome is
the search's business — but it is recorded (§4.7) and counted; the search continues with the
next genome (`REFUSED_BY_GATE`, a per-candidate outcome: §3c's taxonomy deliberately excludes
it from the epoch-ending kinds). A timeout, a malformed reply, or any token/`seq`
inconsistency is a `PROTOCOL` end (§3c).

### 4.4 Link 2 — the staged bytes, before any DMA

After staging, the application re-reads the three staged streams **from DDR through the
non-cacheable mapping**, word by word, and computes `staged_sha256` (frames domain) and
`staged_stream_sha256` (stream domain), both as `run_log` defines them. **`staged_sha256` must
equal the notary's `commit`** — this is the point at which the application's own construction
is bound to what the signer approved, and it happens before the first DMA. Mismatch → STOP
`LINK2_MISMATCH`, no write, epoch ends.

### 4.5 Write and link 3 — the fabric

Per envelope: the P1 executor's transaction, `(WR_BUF|1, PCAP, 534, 0)` — the only legal write
tuple — with `INT_STS` cleared and verified beforehand, `D_P_DONE` waited for with the derived
timeout, the error mask checked, `CTRL` read before and after. Then the pinned readback of
**each of the twelve target frames** (psmap §8a: `(CMD|1, PCAP, 43, 0)`, `(PCAP, DST|1, 0, 202)`,
`(CMD|1, PCAP, 5, 0)`; sentinel prefill of the destination verified before each read), **all
twelve read before judging** (L3 session #1's lesson), `readback_sha256` over the twelve frames
must equal `commit`. Mismatch → STOP `LINK3_MISMATCH`, **no ARM**, epoch ends.

### 4.6 ARM and score

Preconditions as `arm_and_score`: alive, reserved zero, no fault, not busy, `key_loaded`; the
24 payload words written to `0x2100‥215C`; strobe; poll to settle with the derived timeout;
**the nonce must have stepped**. `configuration_valid_hw = 1` → read `HW_COMMIT` (8), the
functional readout (12), `SCORE0‥5`, the heartbeat before and after → `loop_record`.
`configuration_valid_hw = 0` → the PL's refusal is recorded with its fault code and **the
epoch ends** (`STOPPED`): a refused ARM inside a correct loop is an anomaly to report, not a
candidate to retry. The fault code is recorded **as observed and no more** (review #1): it
names the check that fired — `F_ARM_TABLE` the comparator, `F_ARM_AUTH` the MAC verify — not
the cause, which the observation alone cannot diagnose exclusively; diagnosis, if wanted, is
its own session with its own specification, as the L3 diagnostic was. The application never guesses against the MAC;
the sticky fault makes that a property of the hardware, not of the firmware's manners.

The AXI accesses are confined to the runner's map (`Plane`'s allowlist, ported): `0x2000`
(write, bits 6/7 only), `0x2004‥0x2030` (read), `0x2100‥0x215C` (write), `0x2200‥0x226C` (read).
The key words `0x2160‥216C` are **not in the application's map** — as with the runner, a host
test over the firmware source asserts that no code path names them.

### 4.7 Evidence: framed lines, the ring, and audit-on-request

Every step above appends to a `loop_record` (§7) that is (a) written into an **evidence ring**
in the non-cacheable region and (b) printed as one framed line on the console when the
candidate completes or stops. The ring holds the **raw words** — the three re-read streams,
the twelve readback frames, the register values — for the most recent `W` candidates (`W`
pinned in the L5 manifest; 3 × 534 + 12 × 202 + 24 words ≈ 16 KiB per candidate, so `W = 1024`
is 16 MiB of a 256 MiB DDR); the compact record for **every** candidate is streamed live. The
host collector may, at any notary exchange, attach `audit {seq_k}` for any `k` within the last
`W`; the application then prints the raw words of candidate `k` before it proceeds, and the
collector recomputes both link-2 hashes and the link-3 hash from those words and compares them
with the compact record it already holds. The application cannot know which candidates will be
audited, so a self-report it could not back with words would be caught with probability
proportional to the audit rate — a rate the L5 prereg pins, not this document; §7 rule (ix)
writes this down as the bounded guarantee it is. On any `STOPPED` or `PROTOCOL` end the ring
is dumped in full before the terminal line; a `CRASHED` end, by definition, dumps nothing —
§6a defines what, if anything, is recoverable afterwards and with what standing.

Timing is the ARM global timer (`0xF8F00200`), whose frequency the application derives from the
decoded PLLs and records; the host collector timestamps every received line independently. The
per-candidate time budget is **measured at L5**, not assumed here; the expectation is that the
notary round-trip (a `sudo` + Python signer process, ≈ 0.1–0.3 s) dominates the DMA work (sub-ms
per transaction on 17A6, S1–S3) — if so, the host is the loop's clock and §5's transport choice
is also a throughput choice.

## 5. The notary channel

### 5a. Transport

| | T1 — the console (UART1), with the runner as relay | T2 — JTAG DAP mem-AP mailbox, signer-owned |
|---|---|---|
| path | application prints framed request lines; `host/l5_notary.py` (runner principal) parses them, calls `sudo -n -u p3signer host/sign_arm.py sign_genome …`, prints the framed reply | the signer polls a DDR mailbox over `zynq.ahb` (the provisioning config, no Cortex-A target, nothing halted), writes the reply into it |
| principals | runner relays bytes it cannot forge (no `K`); it can only **stall** → bounded wait → epoch ends as HOLD, not KILL | no runner in the path at all |
| perturbation evidence | the console is the channel L2–L4 ran on; its effect on the computing design is what L2 measured alongside PCAP activity | **none**: L2 measured PCAP reads and a write, not sustained DAP traffic into the PS interconnect; T2 would need its own L2-class non-perturbation evidence before a ruling |
| bandwidth | ~200 B per exchange at 115200 8N1 → ms; an audit (§4.7) ≈ 16 KiB → ≈ 1.5 s | higher, but irrelevant until T1 is shown to be the bottleneck |
| recommendation | **T1 for L5's first specification** — one new thing at a time: the loop moves on-board, the channel and its evidence base do not change | recorded as the option if T1's throughput or the relay's presence is judged unacceptable; its own decision |

### 5b. Protocol invariants (either transport)

Framed lines: `P3L5 <type> <seq> <token> <fields…> <crc32>\n`, printable ASCII, one line per
message, where `<token>` is the **full 128-bit session token as 32 hex digits** (review #1
blocker 2: a truncated token cannot claim to bind a 128-bit identity, and 32 bytes per line is
noise at 115200) and `crc32` is over the line body. A receiver drops a CRC-failed line and
counts it; the **drop budget** (per session, pinned in the L5 manifest) makes the console's
known fault rate — psmap kill criterion 3 — a measured quantity, and exceeding it is a
`PROTOCOL` end, never a silent degradation. Exactly one outstanding request; `seq`
strictly increasing from 1; every reply carries the request's `seq`; the token in every line
must be this session's (`identity_page.token`); the nonce in a `sign_request` is the
application's reading and is not verified by the host — a wrong nonce merely yields a tag the
PL rejects, which ends the epoch (liveness, not security). The signer logs every request and
reply (`notary_log`, host-side, timestamps, the runner's relay pid) — this is the host's
independent record of which commits were signed, with which nonce, in which order, and the
post-run validator requires **every ARMed commit in the application's records to have a
signer-log entry with the same `seq` and nonce** (rule (vii), §7).

### 5c. What the notary is not

It does not propose, rank or score. Its refusals are whitelist refusals (safety), not fitness.
It does not compute the host score prediction during the run (that is the post-run validator's
job, so that no prediction can flow back into the search). It does not hold or read the
application's champion. These are the exact senses in which "the host is not in the decision
loop" is claimed — and no other (§10 Q1).

## 6. `zynq-ehw` Claim M1 runtime properties — what transfers

| M1 property (`zynq-ehw/docs/future_plan.md`, "Claim M1") | L5 under this specification |
|---|---|
| long-running operation | yes — bounded by the budget/stop condition, the evidence ring (§4.7) and the console's fault rate; the L5 prereg pins the duration |
| no PC-side candidate selection or fitness computation | **yes, as stated in §5c** — but the host remains the *permission* authority and the key holder (§0, §10 Q1). This is a scope statement, not a footnote: M1's headline was "without a PC in the decision loop"; L5's is "without a host in the *search* loop, with the host as notary" |
| persistent champion / log storage with an explicit NV write budget | **not claimed at L5**: the champion lives in DDR and in the streamed records; the host collector persists. No NAND/TF-card write is part of L5 (new scope, its own decision if ever) |
| automatic recovery without power-cycling | **scoped**: a low-scoring candidate needs no recovery (the next candidate rewrites all twelve frames); a link 2/3 STOP ends the epoch with the fabric restored to the base where possible (§4.0's closing write is attempted on STOP if the DMA path is healthy) and requires a new session; a PL fault is terminal by design (sticky). Recovery of a hung application: the private watchdog (§6a) resets the PS — a new session, not a resumed one. No power-cycle is *required* by any modelled failure; whether one is needed in practice is an L5 measurement |
| replayable evidence after the run | yes — §7's validator replays every candidate from `genome` alone: canonical frames → gate → `commit` == application's `commit` == `hw_candidate_commit`; tables == readout; nonce chain from `NONCE_SEED` through every attempt (the xorshift model already verified on silicon, L3); scores == `p3_oracle` prediction; and cross-checks the signer log |
| telemetry distinguishes slow progress from a stuck run | the application prints a `heartbeat` line every `H` seconds (pinned; e.g. 10 s) with `seq`, candidates completed, refusals, the PL heartbeat word, and the global timer; the collector applies the manifest's pinned heartbeat bounds `[49.5, 50.5] MHz` to consecutive application-reported pairs against the **application's** timer (a sanity envelope — it is not the L2 invariant, which needs host-side timing of AXI reads) and declares the epoch ended (`CRASHED`, §3c) after 3 missed heartbeats |
| replay modes: deterministic (recorded seed) vs autonomous discovery (board-derived seed, recorded) | **L5's first specification uses the host-supplied seed** (`identity_page.seed`) — M1's "test mode". A board-derived seed (entropy source to be named — the PL has none by design; the global timer at start is weak) is a later step and is not the headline of L5 |

### 6a. Watchdog

Recommended **on** (`identity_page.flags.bit1`), the Cortex-A9 private watchdog with a period
of 3 heartbeat intervals, kicked only from the main loop *after* each framed line is written (so
a stuck DMA wait, a stuck notary wait past its own timeout, or a stuck UART all end in a PS
reset → U-Boot banner → epoch ended on both sides). Not kicked from an interrupt. The reviewer
is asked to confirm (§10 Q5); the alternative — no watchdog, the host power-cycles on a
`CRASHED` classification — is the current L2–L4 practice and is acceptable if the reviewer
prefers fewer mechanisms.

**Crash evidence (review #1 blocker 4).** A watchdog reset produces no terminal line and no
ring dump. The epoch's admissible evidence is exactly the framed lines the collector already
holds — complete per candidate up to the last heartbeat, by construction: every completed
candidate printed its compact record before the watchdog was next kicked. The host classifies
the end `CRASHED` (§3c) and writes the `session_summary` itself, with the last received `seq`.
The ring's DDR region MAY be read on the **next** U-Boot session (`md.l`, before anything is
loaded into DDR) as a **post-mortem**: DDR retention across a PS reset is not warranted by
anything this line has pinned, so a post-mortem record carries `standing: diagnostic` and is
never admissible as run evidence — it may suggest where the application died; it proves nothing
about any candidate. The validator refuses a `loop_record` sourced from a post-mortem.

## 7. Contracts this specification adds or amends (proposed; `contracts.md` is not edited by it)

New schemas, all `1.0.0`, each with a validator and a fixture before L5 (§11):

- **`app_identity`** — §3b.
- **`identity_page`** — §3a, the host-side record of what was written and read back, with the
  U-Boot epoch and the `md.l` verification.
- **`sign_request` / `sign_reply` / `refused`** — §4.3 / §5b; the signer log is a list of these
  with host timestamps (**`notary_log`**).
- **`app_oracle_record`** — the application's links 2 and 3 for one candidate: `staged_sha256`,
  `staged_stream_sha256`, `readback_sha256`, the DMA register values per envelope and per
  readback, `audit_available: true|false`, and — when audited — `audit: {words_sha256,
  host_recomputed: {...}, match: bool}`. **Deliberately not `oracle_record`**: a validator that
  requires host-observed links (L2–L4's rules) must never accept an application self-report in
  its place; the two schemas make that a type distinction, not a flag.
- **`loop_record`** — one per candidate: `seq`, `genome` (10 words), `sign_reply` or `refused`,
  `app_oracle_record`, `arm_record` (same fields as today; `signer.principal` stays
  `gate-signer`; `key_loaded_observed` per attempt), `score_record` (same fields), heartbeat
  before/after, timer stamps, and `outcome ∈ {SCORED, REFUSED_BY_GATE, STOP_LINK2, STOP_LINK3,
  REFUSED_BY_PL, STOP_AXI}`.
- **`session_summary`** — opening baseline; counts of SCORED / REFUSED_BY_GATE; champion
  (genome, commit, scores, seq); each closing step (restore, baseline ARM, unsigned control)
  recorded as done or `not_reached` with the §3c kind; `epoch_end: {kind: COMPLETED | STOPPED |
  PROTOCOL | CRASHED, reason, last_seq}`; audit count, rate and results; CRC-dropped line count
  against the drop budget. On `CRASHED` the collector writes it host-side from what it received.

Amendments (MINOR, additive): `run_log` gains `control_plane: uboot|standalone`,
`identity_page`, `app_identity`, `notary_log_sha256`, and the list of `loop_record`s; its
validator gains **rule (vii)**: every `loop_record` with a `score_record` has a `notary_log`
entry with equal `seq`, `commit` and `nonce`, and the nonce sequence across all attempts (scored,
refused-by-PL, and the closing negative control) is exactly the xorshift chain from
`NONCE_SEED`; **rule (viii)**: a `standalone` run log's first scored record is the blank
candidate with the base scores and — **when `epoch_end.kind == COMPLETED`** — its last scored
record is the closing baseline and its last attempt a refused unsigned ARM (for the other
kinds the validator checks the closing steps against §3c's obligations instead); and **rule
(ix)**: the audit is a **bounded** guarantee and the records say so — each `loop_record` is
marked `verified: audited | replayed-only`, `session_summary.audit` reports the audited set
and rate, and any L5 acceptance criterion that quotes per-candidate integrity must quote the
audited set, the hardware-witnessed properties for the rest (3′, the MAC, the nonce chain),
and nothing stronger. Rules (i)–(vi) apply per `loop_record` unchanged, with
`app_oracle_record` in the place of `oracle_record` **only** when `control_plane ==
standalone`.

## 8. Rules that carry over unchanged

Content bits only (the 292 whitelisted addresses; flush frames verbatim; ECC recomputed — link
1 is fabricmap's code). No ICAPE2 (the carrier has none). No startup transition inside any
stream (no SHUTDOWN/START/GRESTORE/JSTART). Exactly the legal DMA tuples and nothing else; every
register written in order; a tuple never left open. The application never writes a clock,
reset, level-shifter or `FPGA_RST_CTRL` register. No Linux. The key register offsets are absent
from the application's map. Rulings are per session, whole-of-session, consumed by any outcome;
the ruling text for L5 is proposed as `whole-of-probe P3-L5` (plus `provisioning P3-K` per
session) and **does not exist**. Every session: power-on, fresh ruling, `verify_principal_boundary`
as the runner (< 6 h) — the board rules in `docs/l3_l4_runbook.md` stand.

## 9. Threat-model delta and stated limits

- **F2 stands, and has a new face.** The application owns DEVCFG and could, in principle, DMA any
  stream — including a full bitstream — into PCAP; so could the L3 runner through the console.
  Neither is prevented by the interlock; both are excluded by the threat model (a compromised
  host / console holder) and by review of the code that is run under a ruling. The L5 image's
  sha is pinned and verified by the host before `go`; that is host evidence, not a hardware
  boundary.
- **F3 (new): links 2 and 3 are the writer's self-report.** Compensations: the PL sweep for the
  six target LUTs (hardware); `staged_sha256 == commit` before any DMA (binds the write to the
  signature, but is checked by the writer); post-run replay; audit-on-request with raw words.
  Not compensated: a self-report about flush frames and non-target bits — exactly as in L3.
- **F4 (new): the relay can stall or drop lines.** Liveness only; every such event ends the epoch
  as HOLD and is counted.
- **Key custody unchanged**: `K` never leaves the signer principal; the application holds no key
  material and its image is public; the nonce prevents pre-signing or replay across sessions.
- The host's post-run prediction of scores is a cross-check, never an input to the search;
  should a future design want the host to *steer*, that is a different claim and a different
  document.

## 10. Questions for the reviewer — positions on record

| # | question | author's position | what the reviewer must rule |
|---|---|---|---|
| Q1 | Is "host as notary" (gate + signer on the host, the search and the PS oracle on the board) an acceptable reading of D1's "no host in the decision loop", given §2/§3c of the architecture? **The definition on offer is narrow and explicit (review #1): the host does not search, rank or score, but the signer still decides which candidates may execute — a permission veto on every candidate. The reviewer is asked to accept or reject exactly this definition, not a paraphrase of it.** | Yes, with §5c and §6 stated as the scope. The alternative — an on-board signer in a *separate* principal (TrustZone secure world holding `K`, or a PL soft-core key holder) — is a new principal boundary and therefore a new decision with its own D4-class review; a single-principal application holding `K` is rejected outright as the arrangement D4 was created to remove. | ACCEPT the scoped claim, or require the on-board-principal design before L5 (which would defer L5 substantially), or REJECT standalone. |
| Q2 | Links 2 and 3 as the application's self-report (`app_oracle_record`) with `staged == commit` before DMA, raw-word ring, audit-on-request, and post-run replay — acceptable as L5's evidence standard? | Yes, as a **declared** downgrade from L3's host-observed links, with the type distinction in §7 so that no L2–L4 rule is weakened. | ACCEPT; or require live raw upload for every candidate (T1 bandwidth then bounds the loop at ≈ 1.5 s/candidate); or require T2 with its own perturbation evidence. |
| Q3 | Transport: T1 console + relay, or T2 JTAG mailbox? | T1 first (§5a). | Confirm; if T2, confirm that an L2-class non-perturbation session for DAP traffic precedes any L5 ruling. |
| Q4 | Session brackets (§4.0): opening baseline as positive control, closing baseline as restore, closing unsigned ARM as the negative control — sufficient as L5's per-session controls? | Yes; the sticky fault makes the negative control naturally last. `replay`/`other_candidate`/`wrong_key` were established at L3 and are not repeated per L5 session. | Confirm, or name additional per-session controls. |
| Q5 | Watchdog on (§6a) or off? | On, kicked only from the main loop after each framed line. | Confirm. |
| Q6 | Seed: host-supplied (test mode) for L5's first specification; board-derived later? | Yes; M1's own taxonomy calls the host seed a test mode and L5 does not claim autonomous discovery. | Confirm; and rule whether L5's headline should say so in its title. |
| Q7 | The genome contract (§4.1: 292 bits, ascending `(far, word, bit)`, 10 words) and the `derive` function as the single point where the application's construction and the signer's verdict meet — is the pinned C-vs-Python corpus (§4.2, §11) the right exit gate for that? | Yes: if `derive` differs by one bit between the two sides, link 2's `staged == commit` catches it at run time, but only after a board session was spent; the corpus test catches it host-side. | Confirm the corpus (known answer, blank, N random) and N. |

## 11. What would come next — none of it authorised by this document

1. Non-author review of this document; verdicts on Q1–Q7 recorded in `docs/decisions.md` D1.
2. Host-only, on ACCEPT: `contracts.md` 1.1 with the §7 schemas, their validators and fixtures;
   `host/sign_arm.py sign_genome` (gate + tables + tag from a genome; the signer's own gate);
   `host/l5_notary.py` (relay + collector + `notary_log`); a Python reference of the application's
   loop against the existing fake board (the fake proves sequencing and refusals, not the PL or
   transport — as for L3); the C↔Python pinned corpus for `derive`/ECC/streams/hashes; a firmware
   source audit test (no key offsets, no clock/reset writes, only legal DMA tuples).
3. L5 design record (`docs/l5_design.md`): image layout, buffer map, linker map test, build
   recipe **including the toolchain decision** (no `arm-none-eabi-gcc` on this host today), the
   L5 manifest (`W`, `H`, buffers, image sha), the per-candidate time budget as a thing to measure.
4. Whole-line gate re-review (the "Re-review delta" form of `docs/whole_line_gate_review.md`)
   over D1 + L5 design.
5. A ruling (`whole-of-probe P3-L5` + `provisioning P3-K`), power-on, verifier, one bounded
   session (small budget) before any long run; its findings document.

Nothing in 2–5 begins on the strength of this document.

## 12. Change log

- **v0.2 (2026-08-31)** — after review #1 (**HOLD**, verbatim in `docs/d1_review_result.md`),
  all four blockers and the four secondary items: (1) the four-kind epoch-end taxonomy in §3c
  (`COMPLETED / STOPPED / PROTOCOL / CRASHED`), `REFUSED_BY_GATE` explicitly per-candidate and
  excluded from it, closing obligations per kind (§4.0), schemas and validator aligned (§7);
  (2) the full 128-bit token in every framed line plus a pinned CRC drop budget (§5b); (3) the
  full 256-bit carrier sha in the identity page and `app_identity`, with the explicit statement
  of what does and does not verify the carrier (§3b); (4) watchdog crash-evidence semantics —
  `CRASHED` verdict, collector-written summary, post-mortem reads `diagnostic`-only, refused by
  the validator as run evidence (§6a). Secondary: closing brackets settled by the taxonomy, not
  timing (§4.0); the audit written as a bounded guarantee — rule (ix) (§4.7, §7); Q1 restated
  as the narrow definition the reviewer must explicitly accept (§10); §4.6's fault codes
  recorded as observed, with no exclusive-cause claim.
- **v0.1 (2026-08-31)** — first draft. Review #1: HOLD.
