"""The gate signer's side of `arm_mac` 1.0.0 — and the principal model.

`KeyHolder` is the ONLY object that reads a key from storage, and it is constructed from a
path that, in production, is readable by the `gate-signer` OS user alone (`p3_architecture`
§3c). The runner never receives a `KeyHolder`; it receives an `ArmPayload` it can write to
the PL but cannot produce. Tests model the two principals with fixtures (a readable and an
unreadable key path), never with real OS users (owner's limit).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .siphash import siphash128

TAG_BYTES = 16
NONCE_BYTES = 8
COMMIT_BYTES = 32
TABLES = 6


class SignerRefusal(Exception):
    pass


class KeyHolder:
    """Holds K in memory for the process lifetime; refuses if the file is not private."""

    __slots__ = ("_k", "key_id")

    def __init__(self, path: Path):
        try:
            st = os.stat(path)
        except OSError as exc:
            raise SignerRefusal(f"key not available: {exc}") from None
        if st.st_mode & 0o077:
            raise SignerRefusal(f"{path} is readable by others (mode {st.st_mode & 0o777:o}); refused")
        data = path.read_bytes()
        if len(data) != 16:
            raise SignerRefusal("key file must hold exactly 16 bytes")
        self._k = data
        import hashlib
        self.key_id = hashlib.sha256(data).hexdigest()   # never K itself

    def __repr__(self) -> str:
        return f"<KeyHolder key_id={self.key_id[:12]}…>"

    def _sign(self, message: bytes) -> bytes:
        return siphash128(self._k, message)


@dataclass(frozen=True)
class ArmPayload:
    candidate_commit: bytes       # 32 bytes: the FULL candidate_sha256
    expected_tables: tuple        # six ints, 64-bit each
    nonce: bytes                  # 8 bytes, read from the PL this session
    tag: bytes                    # 16 bytes

    def message(self) -> bytes:
        return arm_message(self.candidate_commit, self.expected_tables, self.nonce)

    def words(self) -> list[int]:
        """The 24 AXI words in the order the PL's staging registers expect."""
        out = [int.from_bytes(self.candidate_commit[i:i + 4], "big") for i in range(0, 32, 4)]
        for t in self.expected_tables:
            out += [(t >> 32) & 0xFFFFFFFF, t & 0xFFFFFFFF]
        out += [int.from_bytes(self.tag[i:i + 4], "big") for i in range(0, 16, 4)]
        return out


def arm_message(candidate_commit: bytes, expected_tables, nonce: bytes) -> bytes:
    if len(candidate_commit) != COMMIT_BYTES:
        raise SignerRefusal("candidate_commit must be the full 32-byte candidate_sha256")
    if len(expected_tables) != TABLES or any(not (0 <= t < 1 << 64) for t in expected_tables):
        raise SignerRefusal("expected_tables must be six 64-bit values")
    if len(nonce) != NONCE_BYTES:
        raise SignerRefusal("nonce must be 8 bytes")
    return candidate_commit + b"".join(t.to_bytes(8, "big") for t in expected_tables) + nonce


def sign_arm(holder: KeyHolder, gate_verdict: dict, candidate_commit: bytes,
             expected_tables, nonce: bytes) -> ArmPayload:
    """Only a writable verdict is signed; the verdict's hash must be the commitment."""
    if not isinstance(holder, KeyHolder):
        raise SignerRefusal("signing needs a KeyHolder; the runner does not have one")
    if not gate_verdict.get("writable"):
        raise SignerRefusal("the gate did not pass this candidate; nothing is signed")
    if bytes.fromhex(gate_verdict["candidate_sha256"]) != candidate_commit:
        raise SignerRefusal("candidate_commit is not the gate verdict's candidate_sha256")
    tag = holder._sign(arm_message(candidate_commit, expected_tables, nonce))
    return ArmPayload(candidate_commit, tuple(expected_tables), nonce, tag)


def verify_arm(holder: KeyHolder, payload: ArmPayload, pl_nonce: bytes) -> bool:
    """What the PL does in hardware, modelled on the host for tests and fixtures."""
    if payload.nonce != pl_nonce:
        return False
    return holder._sign(payload.message()) == payload.tag
