# L3 / L4 runbook — one session at a time, each under its own ruling

All host-side preparation is done (`docs/l3_design.md`, `host/l4_runner.py`). Every
on-board session below needs: the board **power-cycled**, a fresh
`principal_boundary` record (**run as the runner, < 6 h**), one `whole-of-probe P3-L3`
(or `P3-L4`) ruling, and — for every session that provisions a key — one `provisioning
P3-K` ruling handed to the signer. Runs are launched in the background, never under a
shell timeout. Faults are sticky: one negative control per session.

```bash
# before every session (as the runner):
python3 host/verify_principal_boundary.py --out evidence/boundary/principal_boundary_<date>.json
```

| # | session | ruling(s) | command (add `--boundary <record> --manifest builds/p3/carrier_manifest.json --bitstream builds/p3/p3.bit --out evidence/l3_17A6_<date>`) | expected |
|---|---|---|---|---|
| 1 | `unprovisioned` (pre-positive; **no provisioning**, first L3 board contact) | P3-L3 | `python3 host/l3_runner.py --ruling <r> --negative unprovisioned` | chain to link 3 PASS; ARM → `F_ARM_NOKEY` (12), nonce consumed, no score |
| 2 | positive + `unsigned` | P3-L3 + **P3-K** (first JTAG mem-AP provisioning) | `… --provision-ruling <k> --negative unsigned` | score = `[35,22,20,20,20,18]`, `HW_COMMIT` = gate hash; then `F_ARM_AUTH` |
| 3 | positive + `replay` | P3-L3 + P3-K | `… --provision-ruling <k> --negative replay` | as 2, then `F_ARM_AUTH` |
| 4 | positive + `other_candidate` | P3-L3 + P3-K | `… --provision-ruling <k> --negative other_candidate` | as 2, then `F_ARM_AUTH` |
| 5 | `wrong_key` (pre-positive; signer provisions `K_control.bin`) | P3-L3 + P3-K | `… --provision-ruling <k> --negative wrong_key --wrong-key /var/lib/p3signer/keys/K_control.bin` | ARM → `F_ARM_AUTH`, no score |
| 6 (opt.) | positive + `wrong_table` | P3-L3 + P3-K | `… --provision-ruling <k> --negative wrong_table` | then `F_ARM_TABLE` (15) |
| L4 | corrupt staging → restore → baseline | P3-L4 + P3-K | `python3 host/l4_runner.py --ruling <r> --provision-ruling <k> …` | link 2 STOP with no DMA; 12 frames read back blank; baseline `[18,22,20,20,20,18]` |

Host-only, no ruling: `python3 host/l4_runner.py --gate-refused-only --out evidence/l4_gate_refused --manifest builds/p3/carrier_manifest.json`.

Ruling JSON shape (psmap's): `{"ruling": "<text>", "boardid": "17A6", "granted_by": "…", "date": "<unique>"}`;
the runner claims it O_EXCL and records the outcome whatever happens.

Kill criteria in force (`p3_architecture.md` §7): a score without `configuration_valid_hw`,
a negative control that scores, a refused candidate reaching the fabric.
