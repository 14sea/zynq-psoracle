# L0 architecture review — result

## Verdict, 2026-08-29 (owner-designated non-author review), on `4d92809`: **REJECT**

Recorded in substance from the reviewer's text; the reviewer's own wording where it matters:

> §3's `configuration_valid`, although computed by the host and recomputed by the run-log
> validator, **is not consumed or enforced by the PL scorer itself.** If the host issues
> ARM directly, the PL can still produce a score while `configuration_valid == false`; the
> validator can only reject the record afterwards — it cannot prevent the score from
> happening. So: links 1–3 are fully observed, the host has an explicit predicate, **but
> the interlock's "no ARM / no score" constraint is not enforced by a trusted boundary.**
> This is exactly what the original specification forbids: moving the interlock to the
> host and replacing a hard gate with process discipline.

> To pass, §3 needs a **trusted enforcement point** — the PL, or a hardware / trusted
> control plane the runner cannot bypass — such that ARM/score **physically cannot take
> effect** while the predicate is false. Adding validators, logs or tests does not change
> the conclusion.

Other three questions (`decisions.md`): heartbeat envelope — **ACCEPT both bounds**, pinned
from the L2 no-read baseline. Link 2 — **ACCEPT** full staged stream and candidate frames
recorded and hashed separately, neither substituting for the other. L3 known answer —
**ACCEPT** fabricmap's LUT0 candidate, pinned only after L1 regenerates the frame table and
scorer.

Standing after the verdict: **L0 KILL / not passed.** D1, D3, remote, L1 build, any board
operation: not authorised.

## Authors' acknowledgement (not reviewer text)

Accepted without dispute. The draft's §3 answered "who observed the bytes" and left "who
can stop the score" to software; §3.4 of `claimb_findings.md` had already said a verdict
with no hardware channel is a bypass however well it is logged. The redesign direction is
proposed in `docs/p3_enforcement_proposal.md` and is **not adopted** until the owner rules
on it; §3 of the architecture is not rewritten in this commit.
