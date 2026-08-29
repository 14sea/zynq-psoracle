#!/usr/bin/env python3
"""The gate-signer principal, as a separate process (docs/decisions.md D4).

Reads one JSON request on stdin and answers on stdout. Two operations:
  {"op": "sign", gate_verdict, candidate_commit, expected_tables, nonce}  → tag + 24 words
  {"op": "provision", "execute": bool, ["ruling": path]}                    → the key written
     into the PL's write-once register over JTAG (host/provision_key_jtag.py); execution is
     refused unless a ruling with the text "provisioning P3-K" is given (a board action).
It is the only program that opens `K`; the runner (`l3_runner.py`) never imports
`KeyHolder`. Refusals are the signer's and are returned as a non-zero exit with the reason
on stderr. Key words never appear in any answer.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R))
from validators import signer as sg  # noqa: E402
sys.path.insert(0, str(R / "host")); sys.path.insert(0, str(R / "scripts"))
import provision_key_jtag as pk  # noqa: E402

PROVISION_RULING_TEXT = "provisioning P3-K"


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: sign_arm.py <key_path>  (request JSON on stdin)", file=sys.stderr)
        return 2
    req = json.load(sys.stdin)
    try:
        holder = sg.KeyHolder(Path(sys.argv[1]))
        if req.get("op", "sign") == "provision":
            execute = bool(req.get("execute"))
            if execute:
                import pcap_probe_runner as pr
                pr.check_ruling(Path(req["ruling"]), text=PROVISION_RULING_TEXT)   # refuses without it
            res = pk.run(holder._k, execute)
            json.dump({"provision": res, "key_id": holder.key_id}, sys.stdout)
            return 0 if res.get("rc", 0) == 0 else 1
        payload = sg.sign_arm(holder, req["gate_verdict"], bytes.fromhex(req["candidate_commit"]),
                              [int(t, 16) for t in req["expected_tables"]], bytes.fromhex(req["nonce"]))
    except (sg.SignerRefusal, OSError, ValueError, KeyError) as exc:
        print(f"signer refused: {exc}", file=sys.stderr)
        return 1
    json.dump({"tag": payload.tag.hex(), "words": payload.words(), "key_id": holder.key_id}, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
