#!/usr/bin/env python3
"""Vectors for tb_p3_siphash.v from the Python reference (validators/siphash.py).

Each line: key(32 hex, little-endian int of the 16 key bytes) msg(20 words big-endian, 160 hex)
nonce(16 hex, little-endian int of the 8 nonce bytes) tag(32 hex: out0 then out1, each as the
64-bit LE integer). The RTL consumes the same byte stream; agreement is the test.
"""
import random, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from validators.siphash import siphash128

rng = random.Random(0x5EED)
out = []
for i in range(40):
    key = bytes(range(16)) if i % 2 == 0 else bytes(range(0x10, 0x20))     # KEY_A / KEY_B
    words = [rng.getrandbits(32) for _ in range(20)]
    nonce = bytes(rng.getrandbits(8) for _ in range(8))
    msg = b"".join(w.to_bytes(4, "big") for w in words) + nonce
    tag = siphash128(key, msg)
    out.append(f"{int.from_bytes(key,'little'):032x} {''.join(f'{w:08x}' for w in words)} "
               f"{int.from_bytes(nonce,'little'):016x} "
               f"{int.from_bytes(tag[:8],'little'):016x}{int.from_bytes(tag[8:],'little'):016x}")
Path(__file__).with_name("siphash_vectors.txt").write_text("\n".join(out) + "\n")
print(len(out), "vectors")
