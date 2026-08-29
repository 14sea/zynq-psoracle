"""SipHash-2-4 with 64- and 128-bit output — the `arm_mac` 1.0.0 reference implementation.

Pure Python, written from the SipHash specification (Aumasson & Bernstein) and checked
against the published reference vectors (`veorq/SipHash`, `vectors.h`: key = bytes
0x00..0x0f, message i = bytes 0x00..i-1) in `tests/test_siphash.py`. Nothing in this
module holds a key; the key is an argument, and the only module that reads one from
storage is `validators/signer.py`.
"""

from __future__ import annotations

MASK = 0xFFFFFFFFFFFFFFFF


def _rotl(x: int, b: int) -> int:
    return ((x << b) | (x >> (64 - b))) & MASK


def _round(v: list[int]) -> None:
    v[0] = (v[0] + v[1]) & MASK; v[1] = _rotl(v[1], 13); v[1] ^= v[0]; v[0] = _rotl(v[0], 32)
    v[2] = (v[2] + v[3]) & MASK; v[3] = _rotl(v[3], 16); v[3] ^= v[2]
    v[0] = (v[0] + v[3]) & MASK; v[3] = _rotl(v[3], 21); v[3] ^= v[0]
    v[2] = (v[2] + v[1]) & MASK; v[1] = _rotl(v[1], 17); v[1] ^= v[2]; v[2] = _rotl(v[2], 32)


def siphash(key: bytes, msg: bytes, outlen: int = 8, c: int = 2, d: int = 4) -> bytes:
    if len(key) != 16:
        raise ValueError("SipHash key must be 16 bytes")
    if outlen not in (8, 16):
        raise ValueError("outlen must be 8 or 16")
    k0 = int.from_bytes(key[:8], "little"); k1 = int.from_bytes(key[8:], "little")
    v = [0x736f6d6570736575 ^ k0, 0x646f72616e646f6d ^ k1,
         0x6c7967656e657261 ^ k0, 0x7465646279746573 ^ k1]
    if outlen == 16:
        v[1] ^= 0xEE
    n = len(msg)
    full = n - (n % 8)
    for i in range(0, full, 8):
        m = int.from_bytes(msg[i:i + 8], "little")
        v[3] ^= m
        for _ in range(c):
            _round(v)
        v[0] ^= m
    tail = (n & 0xFF) << 56
    rest = msg[full:]
    for i, byte in enumerate(rest):
        tail |= byte << (8 * i)
    v[3] ^= tail
    for _ in range(c):
        _round(v)
    v[0] ^= tail
    v[2] ^= 0xEE if outlen == 16 else 0xFF
    for _ in range(d):
        _round(v)
    out = (v[0] ^ v[1] ^ v[2] ^ v[3]).to_bytes(8, "little")
    if outlen == 8:
        return out
    v[1] ^= 0xDD
    for _ in range(d):
        _round(v)
    return out + (v[0] ^ v[1] ^ v[2] ^ v[3]).to_bytes(8, "little")


def siphash128(key: bytes, msg: bytes) -> bytes:
    return siphash(key, msg, outlen=16)
