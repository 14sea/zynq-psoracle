# L4 — fault, restore, baseline on 17A6: findings

## Session (rulings `whole-of-probe P3-L4 2026-08-31-06` + `provisioning P3-K 2026-08-31-06`) — PASS

`evidence/l4_17A6_2026-08-31-06/`, 15 min 7 s, zero disruptions, zero re-reads. Boundary
R1–R5 PASS beforehand. Both rulings consumed.

| step | result |
|---|---|
| link-1 refusal (host-only, `L4_0_gate_refused`) | an illegal candidate (one bit outside the whitelist in `0x00400A20`) → `REFUSED_AT_LINK_1`, kinds `target_frame` + `ecc`; nothing sent |
| corrupted staging (`L4_1_corrupt_stage`) | the known answer's envelope 0 staged (dcache off), then word 74 (word 51 of the first target frame) deliberately rewritten `0x5213` → `0xd213`; link 2 re-read saw `0xd213` ≠ stream → **`REFUSED_AT_LINK_2`**; INT_STS before/after `0x50020004`, `D_P_DONE` clear → **no DMA happened** |
| restore (`L4_2_restore_write_0/1/2`, `L4_3_restore_read_*`) | the blank candidate (= pinned base) staged, re-read, WRITTEN for all three envelopes; **12/12 frames read back as the base** (`readback_sha256 3e24d936…` = the blank candidate's hash) |
| baseline | provisioning rc 0, `key_loaded` observed; signed ARM of the blank candidate → STATUS `0xf54` (cfg_valid_hw ∧ tag_ok ∧ tables_match …), `HW_COMMIT` = the blank candidate's gate hash; **scores `[18, 22, 20, 20, 20, 18]` = host prediction = fabricmap's published `base_restore` train scores**; nonce = model |
| run log | `gate_verdict`, `oracle_record`, `arm_record`, `score_record`; rules (i)–(vi) validate |

Ladder §6 L4 criteria: "every refusal at the named link; restore verified by oracle link 3"
— met; the KILL conditions ("recovery requires power-cycle", "a refused candidate reaches
the fabric") did not occur: the corrupted buffer never reached the DMA, and the fabric was
restored and re-scored within the same session.

Scope: 17A6, this carrier (`956379fa…`), U-Boot, the fabricmap LUT0 known answer and its
base. The adjudication is the owner's.
