"""The PL's nonce generator, modelled bit-exactly: a 64-bit xorshift stepped after every ARM
attempt (verified or not). The seed is a build-time constant of the carrier (not secret,
recorded in carrier_manifest); the host reads the current nonce before signing."""

MASK = 0xFFFFFFFFFFFFFFFF


def step(x: int) -> int:
    x &= MASK
    x ^= (x << 13) & MASK
    x ^= x >> 7
    x ^= (x << 17) & MASK
    return x & MASK


def sequence(seed: int, n: int) -> list[int]:
    out, x = [], seed & MASK
    for _ in range(n):
        out.append(x)
        x = step(x)
    return out
