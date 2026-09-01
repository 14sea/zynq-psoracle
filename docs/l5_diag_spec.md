# L5 diagnostic session — specification (host-only, written before the board)

**Standing: host-only. This document authorises nothing.** It fixes, in advance, what the
next board session is *for*, what it must produce, and what may and may not be concluded
from it — so its outcome cannot be argued into something afterwards.

## 1. What this session is, and is not

Session 1 (`docs/l5_session1_findings.md`) ended `HOLD STOPPED`: the application wrote the
ARM payload, the tag and the strobe, and the PL did not consume it — the nonce did not step.
The instrumentation that would have said more had been discarded on that path, and the state
itself was unrepresentable. Both are now fixed.

**This is a diagnostic session, not a retry.** Its purpose is to *capture* the register state
around a non-consumed ARM, not to obtain a pass. Concretely:

- **A `PASS` is not the expected outcome and is not the objective.** If the epoch does
  complete, that is itself a finding — an intermittent ARM — and is reported as such, not as
  L5 being adjudicated.
- **Nothing is being changed to make it work.** The runner, the budget, the audit policy and
  the board sequence are identical to session 1 on purpose: an observation is only comparable
  to session 1 if everything except the instrumentation is the same.
- **No ARM is re-issued after a stop**, and no second attempt is made within the session.

### A note on the ruling text

The rulings are `whole-of-probe P3-L5` and `provisioning P3-K` — the rung's own text, not a
`-diag` variant as at L3. That is deliberate and it is a technical fact, not a promotion:
`host/l5_runner.py` checks the ruling against `RULING_TEXT = "whole-of-probe P3-L5"`, and
running the *identical* runner is the whole point, so inventing a new string would mean
changing the runner to accommodate the diagnosis. **The session's standing as diagnostic is
established by this document and by the preregistration's classification of the outcome —
never by the ruling string.**

## 2. Required output (the session fails its own purpose without it)

If the ARM is again not consumed, the evidence **must** contain a `STOP_ARM` `loop_record`
whose `evidence.arm` carries all of:

| field | why it is required |
|---|---|
| `status_after` | the PL's own view immediately after the strobe |
| `fault_after` | whether any gate fault latched at all |
| `ctrl_before`, `ctrl_after` | whether the strobe bit was observable in `CTRL` at all — the single most direct question |
| `writes_issued` | that all 25 writes (20 payload + 4 tag + strobe) were actually issued |
| `nonce_before`, `nonce_after` | equal, by the definition of `STOP_ARM` |

plus, as in session 1: the `IDENT` frame, the notary log, the audit chunks for the candidate,
the full console capture, and the `CPU_CLK_CTRL` preflight. A session that stops at the ARM
**without** a `STOP_ARM` record is an instrumentation failure and is reported as one — the
fix did not work — not as a hardware finding.

## 3. Adjudication — decided now

| observation | what it means | what it does NOT mean |
|---|---|---|
| `STOP_ARM`, `ctrl_after` shows the strobe bit clear and `fault_after == 0` | the write did not reach the gate, or the gate ignored it | nothing about *which*; that needs a further, separate probe |
| `STOP_ARM`, `ctrl_after` shows the strobe latched | the register took the write but the gate did not act on it | not a diagnosis of the gate's internal state |
| `STOP_ARM` with a non-zero `fault_after` | a fault latched without the nonce stepping — a combination L3 never produced | not a root cause |
| the ARM is consumed and the epoch completes | the failure is **intermittent**; session 1's stop stands as observed and unexplained | **not** an L5 PASS, and not evidence that anything was fixed |
| a different stop (link 2, link 3, identity) | a different fault; session 1's question is untouched | nothing about the ARM |

**In every row the root cause remains undetermined until something explains it.** One session
is one observation.

## 4. Procedure

Unchanged from `docs/l5_prereg.md` §4, including the blocking `CPU_CLK_CTRL` preflight, the
`all-self-reporting` audit policy, `N = 8`, watchdog off, and the instrument rules (background
run, no shell timeout, wait by pid, never `pgrep -f`). Power cycle first; the boundary
verifier re-run as the runner (< 6 h); both rulings new and consumed by any outcome.

## 5. Stop-loss

As `docs/l5_prereg.md` §5. A `STOPPED` or `CRASHED` epoch is a **HOLD**. If the session stops
at the ARM a second time with the same register picture, **that is the result** — the next
step is then a decision about a targeted probe, not a third identical session. Repeating an
unchanged experiment after two identical outcomes is not diagnosis.

## 6. What this session cannot establish

It cannot establish why an ARM was not consumed — only what the registers looked like when it
happened. It says nothing about the PL's internals, nothing about timing, and nothing about
the interlock claim, which rests on L3 and is untouched. `p3_app.c`'s use of the wire unit
remains checked only statically.
