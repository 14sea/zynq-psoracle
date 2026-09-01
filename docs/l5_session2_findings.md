# L5 session 2 (17A6, ruling P3-L5 2026-09-01-02) — HOLD (CRASHED). My instrumentation caused it.

**Outcome: `HOLD CRASHED: silence > 30s`, `last_seq = 0`, zero `loop_record`s. The required
output of `docs/l5_diag_spec.md` §2 was NOT produced.** Per that section this is reported as
an **instrumentation failure — the fix did not work — and not as a hardware finding.**
Evidence: `evidence/l5_17A6_2026-09-01-02/`.

**The cause is a defect I introduced in the instrumentation batch.** It is not a new fact
about the board, and session 1's open question is untouched.

## 1. What happened

The console carries exactly 26 frames and then stops dead:

| frame | count |
|---|---|
| `IDENT` | 1 (no findings, `STATUS 0x900`) |
| `SIGNREQ` | 1 (answered by the real signer — 1 notary entry) |
| `HB` | 16 |
| `AUDIT` | 8 (the full `streams+readback` span, as in session 1) |

**The last line is `AUDIT` chunk 7, then silence.** The collector declared `CRASHED` after
30 s, wrote the summary itself, and the runner stopped without restoring — correct behaviour
under the preregistration.

The application therefore died between serving the audit and emitting the record, which is
precisely where the instrumentation batch inserted its first new instruction.

## 2. The defect

`arm_attempt` now begins with:

```c
*ctrl_before = axi_read(P3_CTRL);      /* added by the instrumentation batch */
```

**`CTRL` (`0x2000`) is write-only.** `rtl/p3_axil.v` says so in its own header:

```
0x2000  CTRL   W: bit6 arm_strobe, bit7 mode_holdout   (anything else: SLVERR)
...
any other address: SLVERR on read and on write
```

and `p3_app.c` states the consequence: *"An undecoded access is SLVERR and, on this board, a
data abort (zynq-psmap P2), so the allowlist is checked at the accessor rather than trusted
from the call sites."* The read takes a data abort and the application dies silently — no
record, no `TERM`, which is exactly the observed signature.

**The allowlist that would have stopped it was one I widened myself.** `axi_readable()`
refused `CTRL` until this batch added it.

### The false premise

I justified the change with: *"the RTL already exposed it read-only and L3's host read it
over `md.l`."* That is wrong. The `md.l CTRL` in `host/l3_runner.py` reads
`pcap_probe_plan.REG["CTRL"]` = **`0xF8007000`, the DEVCFG control register** — a different
register in a different peripheral from the PL carrier's `0x2000`. I conflated two registers
that share a name, and widened a safety allowlist on the strength of it without checking the
RTL, which states the answer in its first ten lines.

This is a "confirm, don't guess" failure of exactly the kind this line's audits exist to
catch, committed while editing the audit's own allowlist.

## 3. Cost

- Rulings `P3-L5 2026-09-01-02` and `P3-K 2026-09-01-02` are **consumed on my defect**, not
  on a board question.
- One power cycle and one session spent.
- **Nothing was learned about the non-consumed ARM.** Session 1's finding stands exactly as
  it was: root cause undetermined.

Not damaged: the board came up clean, identity held, provisioning succeeded, links 2 and 3
passed and the audit was served — the same eight chunks as session 1. The failure is a clean
data abort in the application, with the fabric left as the carrier's base.

## 4. What this forces, and the decision it needs

`ctrl_before` / `ctrl_after` **cannot be observed from the PS on this carrier**. `CTRL` is
write-only by design, so "did the strobe latch in the register?" — the most direct question
about session 1 — is not answerable without changing the RTL, and changing the RTL means a
new carrier bitstream, which would invalidate the L1/L2/L3 evidence chain that rests on
`956379fa…`. **That is a decision for the owner, not a fix to apply.** The options are, at
least:

1. **Drop the two fields.** Keep `STATUS`, `FAULT`, both nonces and `writes_issued`; accept
   that the strobe's fate in the register is unobservable. Smallest change; loses the most
   direct diagnostic.
2. **A read-only mirror of the last CTRL write** added to the RTL at a new offset. Answers
   the question directly, but is a new carrier build and a new L1/L2 evidence question.
3. **Observe the strobe externally over JTAG** rather than from the PS, as the L3 diagnostic
   did for the fabric — no RTL change, but its own non-perturbation argument to make.

## 5. What I am not doing

Not fixing and re-running. The defect is understood, but the repair is entangled with the
decision in §4, and I have just spent a ruling on my own error; spending another before that
decision would repeat the mistake at a higher cost. No firmware, RTL, specification or
preregistration change has been made in response to this session.

## 6. Standing

- **HOLD (CRASHED)** per `docs/l5_prereg.md` §5 — never a PASS, and by itself never a KILL.
  No falsification condition was met.
- Both `-02` rulings consumed; a further session needs a power cycle and new ones.
- Pinned image remains `8390c463…` — it is the image that produced this result and stays
  identifiable, exactly as `d3828a8c…` does for session 1.
- L3's hardware-enforced interlock result is untouched. L5's runtime property remains untested.
