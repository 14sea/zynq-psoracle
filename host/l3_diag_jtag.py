#!/usr/bin/env python3
"""Terminal JTAG read for the L3 diagnostic — runs AS THE SIGNER PRINCIPAL (pod owner).

    sudo -n -u p3signer python3 host/l3_diag_jtag.py <evidence_dir>

Reads `<evidence_dir>/jtag_request.json` (FAR list + the seal's sha256, written by the
runner after the PCAP phase was sealed), runs zynq-psmap's config-space-only JTAG probe
(`scripts/probe_jtag_config_read.py`, `scripts/jtag_config_only.cfg` — no DAP, no
targets), and prints the probe's record as JSON on stdout. Nothing is written into the
runner's evidence directory by this user; the runner saves the stdout as `jtag.json`.
Terminal: nothing touches the board after it.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

R = Path(__file__).resolve().parent.parent
PROBE, CFG = R / "scripts/probe_jtag_config_read.py", R / "scripts/jtag_config_only.cfg"


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: l3_diag_jtag.py <evidence_dir>", file=sys.stderr); return 2
    req_path = Path(sys.argv[1]) / "jtag_request.json"
    try:
        req = json.loads(req_path.read_text())
    except (OSError, ValueError) as exc:
        print(f"no readable jtag_request.json: {exc}", file=sys.stderr); return 2
    fars = [int(f, 16) for f in req["fars"]]
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "jtag.json"
        argv = [sys.executable, str(PROBE), "--cfg", str(CFG), "--out", str(out)]
        for far in fars:
            argv += ["--far", f"{far:#010x}"]
        p = subprocess.run(argv, capture_output=True, text=True, timeout=900)
        if not out.exists():
            print(json.dumps({"verdict": "NO_RECORD", "rc": p.returncode, "stderr": p.stderr[-600:]})); return 1
        rec = json.loads(out.read_text())
    rec["request"] = req
    print(json.dumps(rec))
    return 0 if rec.get("verdict") == "READ" else 1


if __name__ == "__main__":
    sys.exit(main())
