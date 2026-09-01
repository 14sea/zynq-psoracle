#!/usr/bin/env python3
"""Read-only SLCR clock words over the U-Boot control plane, under a `read-only SLCR P3-CLK`
ruling: CLK_621_TRUE (0xF80001C4), CPU_CLK_CTRL (0xF8000120), ARM_PLL_CTRL (0xF8000100) in
ONE session so the three are self-consistent, decoded, and written as evidence.

Why: CLK_621_TRUE was the one clock observation the L5 line left unread (session 1's
preflight covered CPU_CLK_CTRL only). It selects whether CPU_3x2x/2x/1x derive 6:2:1 or
4:2:1 from CPU_6x4x; CPU_6x4x itself and PERIPHCLK (= CPU_3x2x = CPU_6x4x/2 in both modes)
do not depend on it. This closes the record, not a dependency. No register is written;
no carrier, provisioning or firmware is involved; the ruling is consumed by any outcome.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R / "scripts")); sys.path.insert(0, str(R / "host")); sys.path.insert(0, str(R))
import board_session as bsn  # noqa: E402
import pcap_probe_runner as pr  # noqa: E402

TOOL_VERSION = "slcr_read.py/0.1.0"
RULING_TEXT = "read-only SLCR P3-CLK"
PS_CLK_HZ = 33_333_333
REGS = {"ARM_PLL_CTRL": 0xF8000100, "CPU_CLK_CTRL": 0xF8000120, "CLK_621_TRUE": 0xF80001C4}


def decode(v: dict[str, int]) -> dict:
    pll = v["ARM_PLL_CTRL"]; cpu = v["CPU_CLK_CTRL"]; c621 = v["CLK_621_TRUE"]
    fdiv = (pll >> 12) & 0x7F
    divisor = (cpu >> 8) & 0x3F
    srcsel = (cpu >> 4) & 0x3
    src = {0: "ARM_PLL", 1: "ARM_PLL", 2: "DDR_PLL", 3: "IO_PLL"}[srcsel]
    pll_hz = PS_CLK_HZ * fdiv
    cpu_6x4x = pll_hz / divisor if divisor else None
    ratio = "6:2:1" if c621 & 1 else "4:2:1"
    return {"ARM_PLL_fdiv": fdiv, "ARM_PLL_hz": pll_hz, "CPU_CLK_CTRL_divisor": divisor,
            "CPU_CLK_CTRL_srcsel": src, "CLK_621_TRUE_bit0": c621 & 1, "ratio": ratio,
            "CPU_6x4x_hz": cpu_6x4x,
            "CPU_3x2x_hz": cpu_6x4x / 2 if cpu_6x4x else None,
            "CPU_2x_hz": (cpu_6x4x / 3 if c621 & 1 else cpu_6x4x / 2) if cpu_6x4x else None,
            "CPU_1x_hz": (cpu_6x4x / 6 if c621 & 1 else cpu_6x4x / 4) if cpu_6x4x else None,
            "PERIPHCLK_hz": cpu_6x4x / 2 if cpu_6x4x else None,
            "note": "PERIPHCLK (private timer/WDT) = CPU_3x2x = CPU_6x4x/2 in BOTH ratio modes; "
                    "the ratio bit changes CPU_2x/CPU_1x only. PS_CLK assumed 33.333 MHz (board crystal)."}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ruling", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--port", default=bsn.PORT)
    a = ap.parse_args(argv)
    try:
        ruling = pr.check_ruling(a.ruling, text=RULING_TEXT)
        if a.out.exists():
            raise bsn.SessionRefusal(f"{a.out} exists; evidence is never replaced")
    except (bsn.SessionRefusal, pr.ProbeStop, ValueError, OSError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    consumed = pr.claim_ruling(a.ruling)
    outcome = "CRASHED before a record was written"
    rec = {"tool": TOOL_VERSION, "ruling": ruling, "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "authorised": "read-only: three SLCR words below over U-Boot md.l; identity verified; "
                         "no register written; no carrier, provisioning or firmware",
           "outcome": None}
    try:
        transport = bsn.SerialTransport(a.port)
        try:
            session = bsn.BoardSession(transport)
            rec["identity"] = session.verify_identity()
            session.sync()
            raw = {name: session.read_word(addr) for name, addr in REGS.items()}
            rec["raw"] = {name: {"addr": f"{REGS[name]:#010x}", "value": f"{val:#010x}"}
                          for name, val in raw.items()}
            rec["decoded"] = decode(raw)
            outcome = f"READ: CLK_621_TRUE={raw['CLK_621_TRUE']:#010x} ({rec['decoded']['ratio']})"
        finally:
            transport.close()
    except bsn.SessionRefusal as exc:
        outcome = f"REFUSED: {exc}"
    except Exception as exc:  # noqa: BLE001 — the outcome names it; the ruling is consumed
        outcome = f"CRASHED: {type(exc).__name__}: {exc}"
    finally:
        rec["outcome"] = outcome
        a.out.parent.mkdir(parents=True, exist_ok=True)
        pr.write_record(a.out.parent, a.out.stem, rec)
        pr.record_outcome(consumed, outcome)
    print(outcome)
    return 0 if outcome.startswith("READ") else 1


if __name__ == "__main__":
    sys.exit(main())
