# D4 — a real principal boundary for `K` (proposal after the whole-line HOLD)

> **Status note (2026-08-31):** statements about rung status in this document are historical — what was true when it was written. The canonical status is `docs/status.md`.


Status: proposal, 2026-08-29. Nothing here is implemented; the owner chooses the option.

## 0. What the review found, stated precisely

The authority claim of §3 is *score ⇒ the ARM was signed by the key holder*. Today the key
holder and the runner are the **same OS user**: the runner's process merely does not
construct a `KeyHolder`, but the principal can read `keys/K.bin` and, independently, must
read the keyed bitstream for the setup load — and `K` is a synthesis constant in that
bitstream (LUT INITs in the logic pblock; recoverable offline with the frame map). So the
"only the gate can sign" statement is a process convention, not a boundary. The reviewer
is right; the residual was recorded, but recording it does not discharge it.

Two distinct facts to separate:

- **F1 (key custody)**: can the runner principal obtain `K`? Today yes (file and bitstream).
- **F2 (PL custody)**: whoever holds the console can `fpga loadb` any bitstream, i.e.
  replace the PL with one whose `K` they know. No option below changes F2; F2 is outside
  §3's claim (the claim is about *this* carrier, identified by the setup-load sha the
  session pins) and inside the threat model's exclusion of a compromised host. It is stated
  here so the re-review can rule on it explicitly rather than discover it later.

## 1. Options

### A — runtime key, provisioned by the signer principal over JTAG (recommended)

- **RTL (L1 change)**: remove the `KEY` parameter; add a **write-only, write-once** key
  register (4 words, e.g. `0x2160‥216C`) plus `key_loaded` (STATUS bit 11). ARM is refused
  (`F_ARM_NOKEY`, new fault 12, non-sticky? — sticky is simpler and consistent) until
  `key_loaded`. The latch clears only on reconfiguration. No AXI address ever reads the key
  words back (SLVERR, as today). `K` lives in flip-flops, not in configuration frames, so
  PCAP/JTAG frame readback cannot see it (GCAPTURE is forbidden by the line's rules).
- **Bitstream becomes public**: the dummy build *is* the build; `builds/dummy_key/` is
  renamed; the manifest's `mac.key_id` refers to the provisioned key, not the bitstream.
  The "keyed bitstream = key material" residual disappears outright.
- **Provisioning path**: the signer principal (a separate OS user, `keys/` 0700 to it,
  JTAG pod udev-owned by it, runner user *not* in that group) writes the four words over
  the DAP mem-AP (`zynq.ahb mww 0x43C02160 …`, the AXI path already proven safe under
  U-Boot in the workspace notes) after the runner's setup load and before the first ARM.
  The runner asks for provisioning through the same request/response boundary as signing
  (a small socket service or `sudo -u signer`), never sees `K`, and cannot reach the pod.
- **What the runner can still do**: everything on the console — including F2. It cannot
  read `K`, the key file, or any key-bearing artifact. Testable: file modes, group
  membership, and an AXI read attempt of the key words → SLVERR (host-side refusal + RTL).
- **L3 impact**: a fourth step in the session (provision → verify `key_loaded`) and one
  more negative control, `unprovisioned` (ARM before the key → `F_ARM_NOKEY`, no score).
- **Cost**: RTL + bench + rebuild (one build, no keyed variant), an openocd-driven
  provisioning script for the signer user, the service boundary, udev/user setup on the
  host (owner runs it — sudo), and a JTAG access *during* a U-Boot session, which psmap's
  model so far used only terminally. The mem-AP write does not halt the core; the session
  guards still apply (plmark unchanged, no banner).

### B — signer-owned board service (no RTL change)

The signer user owns the serial port, the key and the keyed bitstream; it performs the
setup load and the ARM signing; the runner user talks to it through an allowlisted
request interface (every U-Boot line the runner may send is checked by the service). This
gives F1 immediately and keeps the RTL, but the *trusted* code grows to include the whole
`BoardSession` and the allowlist, the runner becomes a thin client, and the keyed
bitstream remains key material that the trusted user must guard (its sha in the manifest
is the only public handle). Weaker separation of concerns than A; faster to reach.

### C — encrypted bitstream (AES, BBRAM/eFUSE device key) — rejected

7-series blocks configuration readback when the design is encrypted; link 3 (PCAP frame
readback) would be lost, and BBRAM has no battery on this board (re-program via JTAG every
power-cycle) while eFUSE is permanent. Not compatible with the line.

### D — external/HSM signer — same as A or B for the key file, does not address the bitstream

Only meaningful on top of A (the PL key must still be provisioned).

## 2. Recommendation

**A.** It is the only option under which no artifact the runner can read carries `K`, it
turns the keyed/dummy split into a single public build, and its two new negatives
(`unprovisioned`, key words unreadable) are both bench- and fake-testable. The JTAG
provisioning step is the one new mechanism and it reuses a proven path.

## 3. What changes if A is chosen (for the re-review to pre-approve)

| area | change |
|---|---|
| `rtl/p3_axil.v`, `p3_arm_gate.v`, `p3_siphash.v` | key register (write-once, write-only), `key_loaded`, `F_ARM_NOKEY`; SipHash takes the key from the register |
| `tb/` | `unprovisioned` negative; key words read → SLVERR; re-write of the key ignored |
| `vivado/p3/build_p3.tcl` | no `KEY` generic; one public build; manifest `mac.key_id` = provisioned key's id, `mac.provisioning = "jtag-mem-ap, signer principal"` |
| `host/sign_arm.py` → signer service | runs as the signer user; two requests: `provision(session_id)` (writes the key over JTAG, returns `key_loaded` as observed) and `sign(...)`; runner has no path to `keys/` or the pod |
| `host/l3_runner.py` | after setup load: request provisioning, read STATUS `key_loaded` = 1 before any ARM; record `provisioning` in `oracle_record`/`arm_record` |
| `validators/records.py` | `arm_record.key_loaded_observed`, negative kind `unprovisioned` (expected fault 12) |
| `docs/decisions.md` D4 | rewritten: custody = signer user + pod ownership; bitstream public; F2 stated as out of claim |
| host setup (owner, sudo) | create the signer user, udev rule for the HS3/FT4232H pod, `keys/` ownership |

## 4. Tests that pin the boundary (either option)

- the runner user cannot read `keys/` (mode/ownership test executed as the runner user);
- the runner user is not in the pod's group (A) / has no port access (B);
- the RTL never exposes the key words (bench: read → SLVERR; L1 exit review: no path);
- L3 fake: `unprovisioned` ARM → `F_ARM_NOKEY`, no score (A).
