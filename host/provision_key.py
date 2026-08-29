#!/usr/bin/env python3
"""Provision K (docs/decisions.md D4): 16 CSPRNG bytes into keys/K.bin, mode 0400, and print
the key_id (sha256 of K) and the hex the build script takes as its KEY generic.
keys/ is gitignored; the keyed bitstream built with it is key material too (never committed)."""
import hashlib, os, secrets, sys
from pathlib import Path
R = Path(__file__).resolve().parent.parent
d = R / "keys"; d.mkdir(exist_ok=True); p = d / "K.bin"
if p.exists() and "--rotate" not in sys.argv:
    k = p.read_bytes()
    print("existing key kept (use --rotate to replace)")
else:
    k = secrets.token_bytes(16); p.write_bytes(k); os.chmod(p, 0o400)
print("key_id", hashlib.sha256(k).hexdigest())
print("KEY generic (little-endian int, 32 hex):", f"{int.from_bytes(k, 'little'):032x}")
