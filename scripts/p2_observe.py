#!/usr/bin/env python3
"""P2 — the observable, its allowlist, the FCLK0 decode, and the continuity adjudication.

Host-only, pure. `docs/p2_spec.md` §2–§3 is the contract. Nothing here opens a port.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

TOOL_VERSION = "p2_observe.py/0.1.0"

# ------------------------------------------------------------------ the carrier's registers
AXI_BASE = 0x43C00000
STATUS = AXI_BASE + 0x2004
FAULT = AXI_BASE + 0x2008
SCORES = tuple(AXI_BASE + 0x2010 + 4 * i for i in range(6))
OBSERVABLE = (STATUS, FAULT) + SCORES              # 8 words, this order
ALLOWED_AXI = frozenset(OBSERVABLE)                # anything else in the window is SLVERR → reset
ST_RESERVED = 0xF8000000                           # carrier_axil: bits 31:27 read zero
EXPECTED_FRESH = {STATUS: 0x00000080, FAULT: 0, **{a: 0 for a in SCORES}}   # observation, not a gate

OBSERVE_COMMANDS = tuple(f"md.l {a:#010x} 1" for a in OBSERVABLE)

# ------------------------------------------------------------------ FCLK0, read-only decode
IO_PLL_CTRL, ARM_PLL_CTRL, DDR_PLL_CTRL = 0xF8000108, 0xF8000100, 0xF8000104
FPGA0_CLK_CTRL = 0xF8000170
PS_CLK_MHZ = 33.333333
FCLK0_REQUIRED_MHZ, FCLK0_TOL_MHZ = 50.0, 0.5
FCLK_COMMANDS = tuple(f"md.l {a:#010x} 1" for a in (IO_PLL_CTRL, ARM_PLL_CTRL, DDR_PLL_CTRL,
                                                    FPGA0_CLK_CTRL))


def pll_mhz(ctrl: int, ps_clk_mhz: float = PS_CLK_MHZ) -> float:
    """PLL_FDIV is bits 18:12 of the *_PLL_CTRL register (UG585 register reference)."""
    return ps_clk_mhz * ((ctrl >> 12) & 0x7F)


def decode_fclk(clk_ctrl: int, pll_by_src: dict[int, float]) -> tuple[float, float, int, int]:
    """FPGA0_CLK_CTRL: SRCSEL bits 5:4 (0/1 = IO PLL, 2 = ARM PLL, 3 = DDR PLL),
    DIVISOR0 bits 13:8, DIVISOR1 bits 25:20."""
    src = (clk_ctrl >> 4) & 0x3
    pll = pll_by_src[0 if src in (0, 1) else src]
    div0 = (clk_ctrl >> 8) & 0x3F
    div1 = (clk_ctrl >> 20) & 0x3F
    if div0 == 0 or div1 == 0:
        raise ValueError("a zero divisor is not a clock")
    return pll / div0 / div1, pll, div0, div1


def fclk0_mhz(io_pll: int, arm_pll: int, ddr_pll: int, clk_ctrl: int) -> dict:
    pll_by_src = {0: pll_mhz(io_pll), 2: pll_mhz(arm_pll), 3: pll_mhz(ddr_pll)}
    mhz, pll, d0, d1 = decode_fclk(clk_ctrl, pll_by_src)
    return {"mhz": round(mhz, 3), "pll_mhz": round(pll, 1), "div0": d0, "div1": d1,
            "raw": {"IO_PLL_CTRL": f"{io_pll:#010x}", "ARM_PLL_CTRL": f"{arm_pll:#010x}",
                    "DDR_PLL_CTRL": f"{ddr_pll:#010x}", "FPGA0_CLK_CTRL": f"{clk_ctrl:#010x}"},
            "ok": abs(mhz - FCLK0_REQUIRED_MHZ) <= FCLK0_TOL_MHZ}


# ------------------------------------------------------------------ liveness + continuity


def liveness_problems(sample: dict[int, int]) -> list[str]:
    st = sample[STATUS]
    out = []
    if st & ST_RESERVED:
        out.append(f"STATUS {st:#010x}: bits 31:27 are hard zeros in the carrier; not the carrier answering")
    if st == 0:
        out.append("STATUS reads 0: recovery_required is set out of reset; a live carrier never reads 0")
    return out


def compare(baseline: dict[int, int], sample: dict[int, int]) -> list[dict]:
    """Which words differ, as data — the verdict names them, the record keeps them."""
    return [{"address": f"{a:#010x}", "baseline": f"{baseline[a]:#010x}", "observed": f"{sample[a]:#010x}"}
            for a in OBSERVABLE if baseline[a] != sample[a]]


def adjudicate(baseline: dict[int, int], samples: list[tuple[str, dict[int, int]]]) -> dict:
    """`samples` = [(step_name, words)] in order; the control sample must be first.

    HOLD  (CONTROL_UNSTABLE)      if the control differs from the baseline;
    STOP  (CONTINUITY_VIOLATION)  if any later sample differs, naming the first step;
    PASS                          otherwise.
    """
    if not samples or not samples[0][0].startswith("P2_2_control"):
        raise ValueError("the first sample must be the no-read control")
    for name, s in [("baseline", baseline)] + [(n, w) for n, w in samples]:
        lp = liveness_problems(s)
        if lp:
            return {"verdict": "AXI_NOT_ALIVE", "at": name, "problems": lp}
    ctrl_name, ctrl = samples[0]
    d = compare(baseline, ctrl)
    if d:
        return {"verdict": "CONTROL_UNSTABLE", "at": ctrl_name, "diff": d,
                "detail": "the observable drifted with no PCAP activity; non-discriminating (R5)"}
    for name, s in samples[1:]:
        d = compare(baseline, s)
        if d:
            return {"verdict": "CONTINUITY_VIOLATION", "at": name, "diff": d,
                    "attributable": True,
                    "detail": "first divergence after PCAP activity, with a stable control"}
    return {"verdict": "PASS", "compared": len(samples)}
