"""Record validators for the P3 contracts, and the run-log rules (i)–(v).

These are evidence-consistency checks (`docs/contracts.md`); they never substitute for
the PL MAC gate. A record that fails is REJECTED (`RecordError`), not flagged.
"""

from __future__ import annotations

import hashlib
import json

from .schema import SchemaError, check_envelope

SUPPORTED = {
    "carrier_manifest": "1.0.0", "candidate": "1.0.0", "gate_verdict": "1.0.0",
    "oracle_record": "1.0.0", "arm_record": "1.0.0", "score_record": "1.0.0",
    "run_log": "1.0.0", "negative_control": "1.0.0", "principal_boundary": "1.0.0",
}
REQUIRED = {
    "carrier_manifest": ("bitstream_sha256", "frame_table_sha256", "part", "axi", "target_fars", "no_icap"),
    "candidate": ("carrier_manifest_sha256", "frames", "candidate_sha256", "stream_words", "sequence_sha256"),
    "gate_verdict": ("candidate_sha256", "writable", "findings", "gate_tool", "manifest_sha256"),
    "oracle_record": ("session", "candidate_sha256", "staged_sha256", "staged_stream_sha256", "write",
                      "readback_sha256", "configuration_valid_hw_expected"),
    "arm_record": ("oracle_record_sha256", "gate_verdict_sha256", "epoch", "nonce", "candidate_commit",
                   "expected_tables", "tag", "signer", "axi_before", "key_loaded_observed"),
    "score_record": ("arm_record_sha256", "configuration_valid_hw", "hw_candidate_commit",
                     "functional_readout", "scores", "host_prediction"),
    "run_log": ("ruling_sha256", "records", "epoch_final"),
    "principal_boundary": ("runner_user", "signer_user", "pod_group", "key_store", "checks", "all_passed", "at"),
    "negative_control": ("kind", "arm_record_sha256", "nonce", "configuration_valid_hw", "fault", "scored", "refused_as_expected"),
}
NEGATIVE_KINDS = ("unsigned", "replay", "other_candidate", "wrong_table", "unprovisioned", "wrong_key")
EXPECTED_FAULT = {"unsigned": 13, "replay": 13, "other_candidate": 13, "wrong_table": 15,
                  "unprovisioned": 12, "wrong_key": 13}
# controls that must come BEFORE any valid ARM (the positive attempt itself is expected to be refused)
PRE_CONTROLS = ("unprovisioned", "wrong_key")
HEX64 = 64


class RecordError(ValueError):
    pass


def canonical_sha256(record: dict) -> str:
    return hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate(record: dict) -> dict:
    name = record.get("schema") if isinstance(record, dict) else None
    if name not in SUPPORTED:
        raise RecordError(f"unknown schema {name!r}")
    try:
        known = check_envelope(record, name, SUPPORTED[name], REQUIRED[name])
    except SchemaError as exc:
        raise RecordError(str(exc)) from None
    checker = globals().get(f"_check_{name}")
    if checker:
        checker(known)
    return known


def _hex(v, n, what):
    if not isinstance(v, str) or len(v) != n or any(c not in "0123456789abcdef" for c in v):
        raise RecordError(f"{what} must be {n} lowercase hex chars")


def _check_candidate(r):
    _hex(r["candidate_sha256"], HEX64, "candidate_sha256")
    fars = [f["far"] for f in r["frames"]]
    if fars != sorted(fars):
        raise RecordError("candidate frames must be FAR-ordered")
    for f in r["frames"]:
        if len(f["words"]) != 101:
            raise RecordError("a frame has != 101 words")


def _check_gate_verdict(r):
    _hex(r["candidate_sha256"], HEX64, "candidate_sha256")
    if r["writable"] and r["findings"]:
        raise RecordError("writable with findings is a contradiction")
    for f in r["findings"]:
        if "kind" not in f:
            raise RecordError("a finding without a kind — findings are bucketed by kind, never by text")


def _check_oracle_record(r):
    for k in ("candidate_sha256", "staged_sha256", "staged_stream_sha256", "readback_sha256"):
        _hex(r[k], HEX64, k)
    if r["staged_sha256"] == r["staged_stream_sha256"]:
        raise RecordError("staged frames and staged stream hashes are different domains and cannot coincide")


def _check_arm_record(r):
    _hex(r["candidate_commit"], HEX64, "candidate_commit (the FULL candidate_sha256)")
    _hex(r["nonce"], 16, "nonce")
    _hex(r["tag"], 32, "tag")
    if len(r["expected_tables"]) != 6:
        raise RecordError("expected_tables must have six entries")
    if r["signer"].get("principal") != "gate-signer":
        raise RecordError("arm_record must be signed by the gate-signer principal")
    if not isinstance(r["key_loaded_observed"], bool):
        raise RecordError("key_loaded_observed must be the bool read from STATUS bit 11 before the ARM")


def _check_score_record(r):
    _hex(r["hw_candidate_commit"], HEX64, "hw_candidate_commit")
    if len(r["functional_readout"]) != 6 or len(r["scores"]) != 6 or len(r["host_prediction"]) != 6:
        raise RecordError("six LUTs: readout, scores and prediction must each have six entries")


BOUNDARY_CHECKS = ("R1_runner_is_not_signer", "R2_runner_cannot_read_key", "R3_runner_cannot_open_pod",
                   "R4_signer_reachable_and_holds_key", "R5_signer_in_pod_group")
BOUNDARY_MAX_AGE_S = 6 * 3600


def _check_principal_boundary(r):
    names = [c["check"] for c in r["checks"]]
    if names != list(BOUNDARY_CHECKS):
        raise RecordError(f"principal_boundary checks must be exactly {BOUNDARY_CHECKS}, got {names}")
    if r["runner_user"] == r["signer_user"]:
        raise RecordError("runner and signer are the same user: no boundary")
    if r["all_passed"] is not all(c["passed"] for c in r["checks"]):
        raise RecordError("all_passed disagrees with the checks")


def boundary_established(r: dict, now: float) -> None:
    """What the L3 runner requires before it forms a single line: validated, all passed, fresh."""
    validate(r)
    if not r["all_passed"]:
        raise RecordError("principal boundary NOT established: " + "; ".join(
            f"{c['check']}: {c['detail']}" for c in r["checks"] if not c["passed"]))
    if now - r["at"] > BOUNDARY_MAX_AGE_S:
        raise RecordError("principal_boundary record is older than 6 h; re-run the verifier")


def _check_negative_control(r):
    if r["kind"] not in NEGATIVE_KINDS:
        raise RecordError(f"negative_control kind {r['kind']!r} is not one of {NEGATIVE_KINDS}")
    _hex(r["nonce"], 16, "nonce")
    if r["configuration_valid_hw"] is not False or r["scored"] is not False:
        raise RecordError("a negative control that validated or scored is a KILL, never a record that passes")
    if r["refused_as_expected"] is not (r["fault"] == EXPECTED_FAULT[r["kind"]]):
        raise RecordError(f"refused_as_expected disagrees with fault {r['fault']} for kind {r['kind']}")


# ------------------------------------------------------------------ run_log rules (i)–(vi)


def validate_run_log(log: dict) -> dict:
    """Returns the chain per score; raises RecordError naming the rule that failed."""
    validate(log)
    by_sha = {}
    for rec in log["records"]:
        validate(rec)
        by_sha[canonical_sha256(rec)] = rec
    verdicts = {}
    for score in (r for r in log["records"] if r["schema"] == "score_record"):
        arm = by_sha.get(score["arm_record_sha256"])
        if arm is None:
            raise RecordError("(chain) score_record references no arm_record in this log")
        oracle = by_sha.get(arm["oracle_record_sha256"])
        gate = by_sha.get(arm["gate_verdict_sha256"])
        if oracle is None or gate is None:
            raise RecordError("(chain) arm_record references records not in this log")
        # (i) one epoch across gate verdict, oracle, arm
        epochs = {gate.get("epoch"), oracle["session"].get("epoch"), arm["epoch"]}
        if len(epochs) != 1:
            raise RecordError(f"(i) epoch mismatch across gate/oracle/arm: {sorted(map(str, epochs))}")
        # (ii) hardware-exposed commit == arm commit == gate's candidate hash
        if not (score["hw_candidate_commit"] == arm["candidate_commit"] == gate["candidate_sha256"]):
            raise RecordError("(ii) hw_candidate_commit, arm candidate_commit and gate candidate_sha256 differ")
        # (iii) functional readout == expected tables
        if [int(x, 16) for x in score["functional_readout"]] != [int(x, 16) for x in arm["expected_tables"]]:
            raise RecordError("(iii) functional_readout != expected_tables")
        # (iv) both oracle hashes match the candidate
        if oracle["staged_sha256"] != gate["candidate_sha256"] or oracle["readback_sha256"] != gate["candidate_sha256"]:
            raise RecordError("(iv) oracle staged/readback hash does not match the candidate")
        # (v) the hardware latch was true
        if score["configuration_valid_hw"] is not True:
            raise RecordError("(v) configuration_valid_hw is not true")
        if arm["key_loaded_observed"] is not True:
            raise RecordError("(v) a score with key_loaded_observed false: the PL could not have verified a tag")
        verdicts[canonical_sha256(score)] = {"gate": gate["candidate_sha256"], "epoch": arm["epoch"]}
    # (vi) every on-board negative control in the log was refused by the PL with the expected fault
    for neg in (r for r in log["records"] if r["schema"] == "negative_control"):
        if neg["arm_record_sha256"] not in by_sha:
            raise RecordError("(vi) negative_control references no arm_record in this log")
        if not neg["refused_as_expected"]:
            raise RecordError(f"(vi) negative control {neg['kind']!r} was not refused with fault {EXPECTED_FAULT[neg['kind']]}")
    return verdicts
