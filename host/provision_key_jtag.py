#!/usr/bin/env python3
"""Key provisioning over JTAG (DAP mem-AP), the signer principal's side (D4, option A).

The P3 carrier's key register is write-only and write-once (`rtl/p3_axil.v`): four words at
0x43C02160‥216C (word 0 = key[127:96] of the key as a 128-bit little-endian integer, the
same convention as `p3_siphash`), then CTRL bit 8 (key_commit). The signer writes them
through the DAP's AHB mem-AP — the path the workspace notes prove safe under U-Boot
(`zynq.ahb mww`), which does not halt the core and does not touch the console.

Host-only here: `openocd_tcl()` renders the script; `run()` executes it ONLY with
`execute=True`, which the caller must gate on a provisioning ruling. The rendered script
contains K and must live only where the signer principal can read it.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

R = Path(__file__).resolve().parent.parent
KEY_BASE = 0x43C02160
CTRL = 0x43C02000
KEY_COMMIT = 1 << 8
STATUS = 0x43C02004
DEFAULT_CFG = R / "scripts/jtag_config_only.cfg"


def key_words(key: bytes) -> list[int]:
    if len(key) != 16:
        raise ValueError("K is 16 bytes")
    k = int.from_bytes(key, "little")
    return [(k >> 96) & 0xFFFFFFFF, (k >> 64) & 0xFFFFFFFF, (k >> 32) & 0xFFFFFFFF, k & 0xFFFFFFFF]


def openocd_tcl(key: bytes) -> str:
    lines = ["target create zynq.ahb mem_ap -dap zynq.dap -ap-num 0", "init"]
    for i, w in enumerate(key_words(key)):
        lines.append(f"zynq.ahb mww {KEY_BASE + 4 * i:#010x} {w:#010x}")
    lines.append(f"zynq.ahb mww {CTRL:#010x} {KEY_COMMIT:#010x}")
    lines.append(f"zynq.ahb mdw {STATUS:#010x} 1")     # key_loaded (bit 11) is read back by the signer too
    lines.append("shutdown")
    return "\n".join(lines) + "\n"


def run(key: bytes, execute: bool, cfg: Path = DEFAULT_CFG, speed_khz: int = 1000) -> dict:
    tcl = openocd_tcl(key)
    with tempfile.NamedTemporaryFile("w", suffix=".tcl", delete=False, dir=tempfile.gettempdir()) as f:
        f.write(tcl); path = Path(f.name)
    path.chmod(0o600)
    if not execute:
        return {"prepared": str(path), "executed": False, "words": 4}
    try:
        p = subprocess.run(["openocd", "-f", str(cfg), "-c", f"adapter speed {speed_khz}", "-f", str(path)],
                           capture_output=True, text=True, timeout=60)
        return {"prepared": str(path), "executed": True, "rc": p.returncode,
                "stderr_tail": p.stderr[-800:]}
    finally:
        path.unlink(missing_ok=True)
