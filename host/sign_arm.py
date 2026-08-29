#!/usr/bin/env python3
"""The gate-signer principal, as a separate process (docs/decisions.md D4).

Reads one JSON request on stdin — the gate verdict, the candidate commit, the six expected
tables and the PL nonce — and answers with the ARM payload words on stdout. It is the only
program that opens `K`; the runner (`l3_runner.py`) never imports `KeyHolder`. Refusals
(unwritable verdict, commit ≠ verdict hash, malformed sizes) are the signer's, not the
runner's, and are returned as a non-zero exit with the reason on stderr.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

R = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(R))
from validators import signer as sg  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: sign_arm.py <key_path>  (request JSON on stdin)", file=sys.stderr)
        return 2
    req = json.load(sys.stdin)
    try:
        holder = sg.KeyHolder(Path(sys.argv[1]))
        payload = sg.sign_arm(holder, req["gate_verdict"], bytes.fromhex(req["candidate_commit"]),
                              [int(t, 16) for t in req["expected_tables"]], bytes.fromhex(req["nonce"]))
    except (sg.SignerRefusal, OSError, ValueError, KeyError) as exc:
        print(f"signer refused: {exc}", file=sys.stderr)
        return 1
    json.dump({"tag": payload.tag.hex(), "words": payload.words(), "key_id": holder.key_id}, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
