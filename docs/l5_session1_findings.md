# L5 session 1 (17A6, ruling P3-L5 2026-09-01-01) — HOLD (STOPPED)

**Outcome: `HOLD STOPPED — the nonce did not step: the PL did not consume this ARM`,
at `seq = 1` (the opening baseline). Classified per `docs/l5_prereg.md` §5: a `STOPPED`
epoch is a HOLD. No kill criterion was triggered.** Evidence:
`evidence/l5_17A6_2026-09-01-01/`.

This was the **first execution of the firmware on hardware**. Everything before the ARM
worked; the ARM did not register.

## 1. What the session established on silicon

| step | result |
|---|---|
| principal boundary (as runner) | R1–R5 all PASS; `key_id b4c022a2`, runner cannot read K or open the pod |
| **preflight `CPU_CLK_CTRL`** | `0x1f000200` — DIVISOR 2, SRCSEL 0 (ARM PLL) → **CPU_6x4x = 666.67 MHz** |
| FCLK0 | 50.0 MHz (IO PLL 1600, div 8/4) — in the pinned envelope |
| carrier setup load | sha-gated, accepted |
| provisioning (P3-K) | executed, rc 0; `STATUS` became `0x900` = alive ∧ key_loaded |
| identity page | written and read back word-for-word |
| application image | `d3828a8c…` loaded at `0x0200_0000`, entered with `go` |
| **`IDENT`** | sent, `findings: []`, `pss_idcode 0x13722093` (masked = `0x03722093`), nonce = seed |
| notary round trip | 1 `SIGNREQ` → real signer → `SIGNOK`; the framing held |
| staging + link 2 | passed (`staged == commit`) |
| DMA + link 3 | passed (readback == commit) |
| **audit** | 8 chunks, `span: streams+readback`, 2814 words, CRC clean |
| transport | **zero** disruptions, zero CRC drops, zero re-reads |

### The preflight discharges a long-standing assumption

`CPU_CLK_CTRL = 0x1f000200` gives DIVISOR = 2 from the board-confirmed ARM PLL
(1333.33 MHz), so **CPU_6x4x = 666.67 MHz — exactly the value that had been assumed**. The
manifest's `peripheral_clock_hz = 333333343` therefore rests on a measured figure rather than
a guess. **Not established:** the 6:2:1 vs 4:2:1 selection lives in `CLK_621_TRUE`
(SLCR `0x1C4`), which this read does not cover. Nothing in a watchdog-off session depends on
it, so it stays an open item rather than a blocker.

### The audit is real, and it checks out

This is the first time raw words from the board could be tested against the application's own
claims. Reassembling the 8 chunks (2814 words) and recomputing host-side:

```
signed commit    3e24d93665bb9f29fb43290283a0c01327acd6048b9e979d247e248ee232679b
staged (link 2)  3e24d936…  MATCH
readback (link 3) 3e24d936…  MATCH
```

Both links recompute to the signed commit from the words the application served. The audit
is not a rubber stamp on a self-report: it is independently checkable, and it checked out.
(`3e24d936…` is the blank candidate — the opening baseline — and equals L4's pinned base.)

## 2. The stop

`arm_attempt` wrote the 20 payload words to `0x2100…`, the 4 tag words to `0x2150…`, then the
`ARM_STROBE` (`0x40`) to `CTRL` (`0x2000`), re-read `STATUS`/`FAULT`, and read the nonce
again. **The nonce was unchanged**, so the application stopped: at L3 the PL stepped the
nonce on *every* ARM attempt, including refused ones, so an unchanged nonce means the gate
never saw the strobe.

The mandatory finally ran: `closing.restore = "done"` — the base was written back. No ARM was
attempted after the stop.

### Ruled out

1. **The application's own write allowlist.** A refused offset raises
   `STOP_AXI: write outside the pinned map`; the recorded reason is the nonce check, so the
   writes reached `Xil_Out32`.
2. **A cacheable PL window.** The BSP's `translation_table.S` maps `0x4000_0000–0x7FFF_FFFF`
   as **Strongly Ordered** (`SECT + 0xc02`, C = 0, B = 0). Writes are neither cached nor
   buffered, and reads cannot be stale. *(This was my first hypothesis — it echoed the L3
   D-cache defect — and the BSP source refutes it.)*
3. **Wrong offsets or strobe value.** `CTRL 0x2000`, `ARM_STROBE 0x40`, `PAYLOAD0 0x2100`
   (20 words), `TAG0 0x2150` (4 words) are identical to `host/p3_oracle.py`, i.e. to the
   sequence that armed successfully in all five L3 sessions.

### Not determined

**The root cause is unknown.** AXI *reads* from the application demonstrably work (STATUS,
FAULT, nonce all returned live, correct values); AXI *writes* to the same window appear not
to take effect. What differs from L3 is only *who* issues the write — U-Boot on the PS versus
the standalone application on the PS — and no mechanism for that difference has been
established. Nothing here should be read as a diagnosis.

## 3. An instrumentation gap this session exposed

`arm_attempt` **reads `STATUS` and `FAULT` immediately after the strobe and then discards
them** when the nonce check fails: it returns `-1` and `run_candidate` emits no record. The
two values most likely to identify the cause are precisely the ones not preserved. Same
family as the earlier lessons on this line — the failing path deserves the same evidence
discipline as the passing one. Any next attempt should record the post-strobe `STATUS`,
`FAULT` and `CTRL` read-back before deciding anything.

## 4. Standing

- **HOLD.** Not a PASS, and not a KILL: no falsification condition in §3 of the
  preregistration was met.
- Both rulings are **consumed** (`P3-L5 2026-09-01-01`, `P3-K 2026-09-01-01`). A further
  attempt needs a power cycle and **new** rulings — the consumed pair is never reused.
- The session's own validator run is consistent with a stop at `seq = 1`:
  `{scored: 0, audited: 0, chain_length: 0}`, `audit_policy` vacuously satisfied (no
  self-reporting record was emitted).
- The board was left with the base restored and no ARM outstanding.
- **Nothing about the interlock claim is established or refuted by this session.** L3's
  hardware-enforced interlock result stands unchanged; L5's runtime property is untested.
