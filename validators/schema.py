"""Schema policy (`docs/contracts.md`): MAJOR incompatible, MINOR additive.

A consumer supporting `X.Y` REJECTS a record whose MAJOR ≠ X, ACCEPTS a record whose MAJOR
== X and MINOR ≥ Y or ≤ Y (unknown fields ignored), and always rejects a record whose
`schema` name differs or whose required fields are missing. Field *content* checks live in
`validators/records.py`; this module is the policy only.
"""

from __future__ import annotations

import re

_VER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


class SchemaError(ValueError):
    pass


def parse_version(v: str) -> tuple[int, int, int]:
    m = _VER.match(str(v))
    if not m:
        raise SchemaError(f"schema_version {v!r} is not MAJOR.MINOR.PATCH")
    return tuple(int(x) for x in m.groups())  # type: ignore[return-value]


def check_envelope(record: dict, schema: str, supported: str, required: tuple[str, ...]) -> dict:
    """Policy check. Returns the record's known fields only (unknown MINOR fields ignored)."""
    if not isinstance(record, dict):
        raise SchemaError("record is not an object")
    if record.get("schema") != schema:
        raise SchemaError(f"schema {record.get('schema')!r} != {schema!r}")
    got = parse_version(record.get("schema_version", ""))
    sup = parse_version(supported)
    if got[0] != sup[0]:
        raise SchemaError(f"{schema}: MAJOR {got[0]} is not the supported MAJOR {sup[0]} — rejected")
    missing = [f for f in required if f not in record]
    if missing:
        raise SchemaError(f"{schema}: required fields missing: {missing}")
    known = set(required) | {"schema", "schema_version"}
    return {k: v for k, v in record.items() if k in known}
