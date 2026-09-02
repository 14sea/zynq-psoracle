# Import manifest

Every non-original file in this repository, byte-for-byte, with its sha256, size, origin and
source commit. `tests/test_import_manifest.py` checks each row against the file and requires the
union of this table and the "original" table to equal `git ls-files` exactly (two-way closure).

## Frozen sources

| repository | commit |
|---|---|
| github.com/14sea/zynq-psmap | `191ab0585332e75ac6f15179dc80eeec2d29f9f9` |
| github.com/14sea/zynq-fabricmap | `71666b02d526a6f2c641f1e0aebc15dac0417d4f` |

`zynq-psmap` files keep their original relative paths so that their own `REPO_ROOT`-relative
lookups (`gate_runs/…`, `data/prjxray/…`) resolve unchanged; `zynq-fabricmap` files live under
`imported/fabricmap/` with their original relative paths beneath it, and carry their own
`bitstream_frames.py` / `frame_ecc.py` because the two repositories' copies are different
revisions and neither may be silently substituted for the other.

## Imported files

| path | sha256 | bytes | origin | source path |
|---|---|---|---|---|
| `scripts/board_session.py` | `45e5b1d7c3195fe566987462b787f3149266ddf82c6b530f46d021bbca36f089` | 22830 | zynq-psmap | `scripts/board_session.py` |
| `scripts/pcap_probe_plan.py` | `2820312d9322203e816e239dc858ef077bfc20b5cf5ba15653d167e46f447b7b` | 33569 | zynq-psmap | `scripts/pcap_probe_plan.py` |
| `scripts/pcap_probe_runner.py` | `8de4bfe496e693ec4858a4c14ecda3f3062b57a3ab6ed14e6232c30f255d60c9` | 25150 | zynq-psmap | `scripts/pcap_probe_runner.py` |
| `scripts/pcap_write_plan.py` | `8e547fc48e35b2d287ad5d6ea4183c8a92f70c01084a117d0d70490c951e1a7b` | 16874 | zynq-psmap | `scripts/pcap_write_plan.py` |
| `scripts/p1_runner.py` | `5ea0a19145dd673bbf603b2a1c599b372d915c580bd50ef51c8e720d85d9824e` | 14471 | zynq-psmap | `scripts/p1_runner.py` |
| `scripts/p2_runner.py` | `fd1833157a45646d71b20339d8a8b3a9f525248203a8754f5d9aea7b912a2518` | 8979 | zynq-psmap | `scripts/p2_runner.py` |
| `scripts/p2_observe.py` | `12ad4b7bd0f2e10da3414de1de216bd04706ec7a65f69d46466a61213a2aefb2` | 4912 | zynq-psmap | `scripts/p2_observe.py` |
| `scripts/frame_ecc.py` | `e595c8e0467fd46de90d6f526792cedf09a4eafa1599b2c2c04a3bbcbb78a646` | 6441 | zynq-psmap | `scripts/frame_ecc.py` |
| `scripts/bitstream_frames.py` | `a55246e68e082cbb7d15833e6da134388059ffdb0497c29634a9b740eb9091b3` | 14956 | zynq-psmap | `scripts/bitstream_frames.py` |
| `scripts/diag_pcap_target_select.py` | `d9b7f0a5af18c2cc9ce0578d589e115fba67b3acc2f308e569d6b9523f9021ef` | 7754 | zynq-psmap | `scripts/diag_pcap_target_select.py` |
| `scripts/probe_jtag_config_read.py` | `c3e79a0856ccc821ca35f6a2daa637258075f92b573cf6247d9b745dac1f1122` | 18877 | zynq-psmap | `scripts/probe_jtag_config_read.py` |
| `scripts/jtag_config_only.cfg` | `06e542043996643358e5606d226d9585b1c239325b54e6afb4856d2c6a1b99fa` | 1148 | zynq-psmap | `scripts/jtag_config_only.cfg` |
| `tests/test_s0b_runner.py` | `466723a1a369370472a4f571c627ec8b1ecf1a6264692925b32a77cde4810dd2` | 45353 | zynq-psmap | `tests/test_s0b_runner.py` |
| `tests/test_p1.py` | `5687e45fa243416eae7033d9c9155d292f029e6c223865f1839eafbe24197bb3` | 16890 | zynq-psmap | `tests/test_p1.py` |
| `tests/test_p2.py` | `0b8234eece5bff309e18328edcc51411f5f9a644df84db378fc8db72ce735f80` | 9685 | zynq-psmap | `tests/test_p2.py` |
| `gate_runs/claimb_round1_carrier_2026_08_13_erratum006/carrier.bit` | `8c3369e8e4755da5aceeb7844690d5e132b2e65647004c0a46c0e868e34f0b8a` | 2083863 | zynq-psmap | `gate_runs/claimb_round1_carrier_2026_08_13_erratum006/carrier.bit` |
| `data/prjxray/LICENSE` | `a2010f343487d3f7618affe54f789f5487602331c0a8d03f49e9a7c547cf0499` | 7048 | zynq-psmap | `data/prjxray/LICENSE` |
| `data/prjxray/zynq7/xc7z010/tilegrid.json` | `db16874f2827fc05248ad4a7ef5769deaa8e70158a60c8dd40194c48713479ee` | 4351137 | zynq-psmap | `data/prjxray/zynq7/xc7z010/tilegrid.json` |
| `data/prjxray/zynq7/xc7z010clg400-1/part.yaml` | `43a136f26603c51bd97e9489d223bbc80f278fcc234225ed9fde404402f22683` | 11766 | zynq-psmap | `data/prjxray/zynq7/xc7z010clg400-1/part.yaml` |
| `imported/fabricmap/scripts/gate_candidate.py` | `2d8b15303450fa062836f98ebf1c7b4ab1134c3a680fb20e01a56182be6fc144` | 15277 | zynq-fabricmap | `scripts/gate_candidate.py` |
| `imported/fabricmap/scripts/icap_sequence.py` | `3bb5959b09fa8f73e5d1a3056cb37571c173cabce8a1c3bda5381ec437516564` | 11231 | zynq-fabricmap | `scripts/icap_sequence.py` |
| `imported/fabricmap/scripts/run_log.py` | `6c58e3d1fa95eb5031f20acbbb707151dfd5a3cf96f6a1a6dd1940f12af57092` | 10090 | zynq-fabricmap | `scripts/run_log.py` |
| `imported/fabricmap/scripts/bitstream_frames.py` | `a55246e68e082cbb7d15833e6da134388059ffdb0497c29634a9b740eb9091b3` | 14956 | zynq-fabricmap | `scripts/bitstream_frames.py` |
| `imported/fabricmap/scripts/frame_ecc.py` | `e595c8e0467fd46de90d6f526792cedf09a4eafa1599b2c2c04a3bbcbb78a646` | 6441 | zynq-fabricmap | `scripts/frame_ecc.py` |
| `imported/fabricmap/gate_runs/claimb_round1_carrier_2026_08_13_erratum006/phenotype_manifest.json` | `e45f466d082ccd6f227e6f9be4ce75a4e98c4caa708808c09a77ed32331c10ef` | 74334 | zynq-fabricmap | `gate_runs/claimb_round1_carrier_2026_08_13_erratum006/phenotype_manifest.json` |
| `imported/fabricmap/gate_runs/claimb_round1_carrier_2026_08_13_erratum006/local_map.json` | `56f2b9e81e180eee2540286e4fde797e0d4820a49d10624c10844c38e99d87cb` | 120521 | zynq-fabricmap | `gate_runs/claimb_round1_carrier_2026_08_13_erratum006/local_map.json` |
| `imported/fabricmap/gate_runs/claimb_round1_known_answer_2026_08_14/known_answer.json` | `b115e6be3c44b1500aaf0281bd7f480afa61654a12b1083a778fb9d9cb2f5ef1` | 34941 | zynq-fabricmap | `gate_runs/claimb_round1_known_answer_2026_08_14/known_answer.json` |
| `imported/fabricmap/vivado/carrier/carrier_scorer.v` | `d3fdb3fb026e0f1c7676af54579d6ddb89901c22a36d98695329df127a6ce146` | 7279 | zynq-fabricmap | `vivado/carrier/carrier_scorer.v` |
| `imported/fabricmap/vivado/carrier/tb_carrier_scorer.v` | `b9413ad61e0b7ba62b79bfb36d20d36a4a347f630886f6983b02f7a9cacf65f7` | 9321 | zynq-fabricmap | `vivado/carrier/tb_carrier_scorer.v` |
| `imported/fabricmap/vivado/carrier/carrier_axil.v` | `12cf47ac1fa7d6f997ce24e1c922dcfe10ac8b3b141c1bda0ad7cc8367c1875b` | 12522 | zynq-fabricmap | `vivado/carrier/carrier_axil.v` |
| `imported/fabricmap/vivado/carrier/carrier_axi3_lite.v` | `4a6c3bb8a13693ed3d6a1d5382aff83aa3b74ebedeae99df262343ce32448fdf` | 14356 | zynq-fabricmap | `vivado/carrier/carrier_axi3_lite.v` |
| `imported/fabricmap/vivado/carrier/tb_carrier_axi3.v` | `51bc389725bec9f0b86c80082792d1ca2c918fb038117933bc346478f473ca77` | 17490 | zynq-fabricmap | `vivado/carrier/tb_carrier_axi3.v` |
| `imported/fabricmap/vivado/carrier/carrier.xdc` | `3cdb8446701bfe0a027899a8b9269f496830d1b376f15bbfc322abf1e4fad4ec` | 3098 | zynq-fabricmap | `vivado/carrier/carrier.xdc` |
| `imported/fabricmap/vivado/carrier/build_carrier.tcl` | `ac00e81eae37bcd7ccf3856709e16d965dc17eb863c509772ad028516c0e2aed` | 9276 | zynq-fabricmap | `vivado/carrier/build_carrier.tcl` |
| `imported/fabricmap/vivado/carrier/isolation_checks.tcl` | `9cc79f567e5effeb0ca5ef2a1d6e510a38d6e93f83003c7cdf339d4aa2d8000f` | 11529 | zynq-fabricmap | `vivado/carrier/isolation_checks.tcl` |
| `imported/fabricmap/vivado/carrier/generated/carrier_base_init.vh` | `e5c51727b40b42159dfefad0cc75a2f8b719fb004ec67ecadc4d7dc85d78fa0e` | 768 | zynq-fabricmap | `vivado/carrier/generated/carrier_base_init.vh` |
| `imported/fabricmap/vivado/carrier/generated/carrier_targets.hex` | `1e093c6690b8f57fc53535ed716afd2a82f7ed884526fbee1a0d8eaa9dc5c649` | 420 | zynq-fabricmap | `vivado/carrier/generated/carrier_targets.hex` |
| `imported/fabricmap/vivado/carrier/generated/carrier_vector_order.hex` | `ea308a8da8aee9bba523ac7f5615bb72eb460d5997ef7503a43c7d73daf02473` | 510 | zynq-fabricmap | `vivado/carrier/generated/carrier_vector_order.hex` |
| `imported/fabricmap/vivado/carrier/generated/carrier_constants.json` | `48f79b876a0bfdb449f407692301b29987ef1218fa1adb1fd9a181068765d118` | 2210 | zynq-fabricmap | `vivado/carrier/generated/carrier_constants.json` |

## Files original to this repository

| path |
|---|
| `.gitignore` |
| `LICENSE` |
| `NOTICE` |
| `README.md` |
| `docs/p3_architecture.md` |
| `docs/contracts.md` |
| `docs/decisions.md` |
| `docs/l0_review_result.md` |
| `docs/p3_enforcement_proposal.md` |
| `docs/import_manifest.md` |
| `tests/test_import_manifest.py` |
| `validators/__init__.py` |
| `validators/siphash.py` |
| `validators/schema.py` |
| `validators/lut_table.py` |
| `validators/signer.py` |
| `validators/records.py` |
| `tests/test_siphash.py` |
| `tests/test_schema_policy.py` |
| `tests/test_lut_table.py` |
| `tests/test_signer_principals.py` |
| `tests/test_runlog_validator.py` |
| `validators/nonce.py` |
| `rtl/p3_siphash.v` |
| `tb/gen_siphash_vectors.py` |
| `tb/siphash_vectors.txt` |
| `tb/tb_p3_siphash.v` |
| `rtl/p3_arm_gate.v` |
| `rtl/p3_axil.v` |
| `rtl/p3_core.v` |
| `rtl/p3_top.v` |
| `tb/gen_arm_fixture.py` |
| `tb/arm_fixture.vh` |
| `tb/tb_p3_core.v` |
| `tb/tb_dbg.v` |
| `sim/run_all.sh` |
| `docs/l1_design.md` |
| `vivado/p3/ooc_synth.tcl` |
| `vivado/p3/build_p3.tcl` |
| `host/provision_key.py` |
| `host/gen_carrier_manifest.py` |
| `builds/p3/p3.bit` |
| `builds/p3/p3_build.json` |
| `builds/p3/isolation.txt` |
| `builds/p3/utilization_summary.txt` |
| `builds/p3/timing_summary.txt` |
| `builds/p3/carrier_manifest.json` |
| `tests/test_manifest_artifacts.py` |
| `host/p3_gate.py` |
| `host/p3_oracle.py` |
| `host/sign_arm.py` |
| `host/l3_runner.py` |
| `tests/test_p3_gate.py` |
| `tests/test_p3_oracle.py` |
| `tests/test_l3_runner.py` |
| `host/l2_heartbeat.py` |
| `host/l2_runner.py` |
| `tests/test_l2_runner.py` |
| `docs/l2_spec.md` |
| `docs/l3_design.md` |
| `docs/whole_line_gate_review.md` |
| `docs/whole_line_gate_review_result.md` |
| `docs/d4_principal_boundary.md` |
| `host/provision_key_jtag.py` |
| `scripts/jtag_provision.cfg` |
| `host/principal/99-p3-signer-jtag.rules` |
| `host/principal/setup_signer_principal.sh` |
| `host/verify_principal_boundary.py` |
| `tests/test_principal_boundary.py` |
| `evidence/boundary/principal_boundary_2026-08-29.json` |
| `evidence/boundary/principal_boundary_2026-08-29-02.json` |
| `evidence/l2_17A6_2026-08-29-01/host_note.json` |
| `evidence/l2_17A6_2026-08-29-01/ymodem.log` |
| `docs/l2_findings.md` |
| `evidence/l2_17A6_2026-08-29-02/summary.json` |
| `evidence/l2_17A6_2026-08-29-02/ymodem.log` |
| `evidence/l2_17A6_2026-08-29-02/L2_0_fclk.json` |
| `evidence/l2_17A6_2026-08-29-02/L2_1_baseline.json` |
| `evidence/l2_17A6_2026-08-29-02/L2_2_control.json` |
| `evidence/l2_17A6_2026-08-29-02/L2_3_read_0.json` |
| `evidence/l2_17A6_2026-08-29-02/L2_3_read_1.json` |
| `evidence/l2_17A6_2026-08-29-02/L2_3_read_2.json` |
| `evidence/l2_17A6_2026-08-29-02/L2_3_read_3.json` |
| `evidence/l2_17A6_2026-08-29-02/L2_3_read_4.json` |
| `evidence/l2_17A6_2026-08-29-02/L2_3_read_5.json` |
| `evidence/l2_17A6_2026-08-29-02/L2_3_read_6.json` |
| `evidence/l2_17A6_2026-08-29-02/L2_3_read_7.json` |
| `evidence/l2_17A6_2026-08-29-02/L2_3_read_8.json` |
| `evidence/l2_17A6_2026-08-29-02/L2_3_read_9.json` |
| `evidence/l2_17A6_2026-08-29-02/L2_4_post.json` |
| `evidence/l2_17A6_2026-08-29-02/L2_5_write.json` |
| `evidence/l2_17A6_2026-08-29-02/L2_6_readback.json` |
| `evidence/l2_17A6_2026-08-30-03/summary.json` |
| `evidence/l2_17A6_2026-08-30-03/ymodem.log` |
| `evidence/l2_17A6_2026-08-30-03/L2_0_fclk.json` |
| `evidence/l2_17A6_2026-08-30-03/L2_1_baseline.json` |
| `evidence/l2_17A6_2026-08-30-03/L2_2_control.json` |
| `evidence/l2_17A6_2026-08-30-03/L2_3_read_0.json` |
| `evidence/l2_17A6_2026-08-30-03/L2_3_read_1.json` |
| `evidence/l2_17A6_2026-08-30-03/L2_3_read_2.json` |
| `evidence/l2_17A6_2026-08-30-03/L2_3_read_3.json` |
| `evidence/l2_17A6_2026-08-30-03/L2_3_read_4.json` |
| `evidence/l2_17A6_2026-08-30-03/L2_3_read_5.json` |
| `evidence/l2_17A6_2026-08-30-03/L2_3_read_6.json` |
| `evidence/l2_17A6_2026-08-30-03/L2_3_read_7.json` |
| `evidence/l2_17A6_2026-08-30-03/L2_3_read_8.json` |
| `evidence/l2_17A6_2026-08-30-03/L2_3_read_9.json` |
| `evidence/l2_17A6_2026-08-30-03/L2_4_post.json` |
| `evidence/l2_17A6_2026-08-30-03/L2_5_write.json` |
| `evidence/l2_17A6_2026-08-30-03/L2_6_readback.json` |
| `host/l4_runner.py` |
| `tests/test_l4_runner.py` |
| `docs/l3_l4_runbook.md` |
| `evidence/l4_gate_refused/L4_0_gate_refused.json` |
| `docs/l3_findings.md` |
| `evidence/boundary/principal_boundary_2026-08-30-l3-01.json` |
| `evidence/l3_17A6_2026-08-30-01/summary.json` |
| `evidence/l3_17A6_2026-08-30-01/run_log.json` |
| `evidence/l3_17A6_2026-08-30-01/stop.json` |
| `evidence/l3_17A6_2026-08-30-01/ymodem.log` |
| `docs/l3_diag_spec.md` |
| `docs/d1_standalone_spec.md` |
| `docs/d1_review_result.md` |
| `docs/l5_design.md` |
| `docs/l5_findings.md` |
| `docs/l5_prereg.md` |
| `docs/l5_review_package.md` |
| `manifests/l5_manifest.json` |
| `firmware/Makefile` |
| `firmware/p3_data.h` |
| `firmware/p3_derive.h` |
| `firmware/p3_derive.c` |
| `firmware/p3_app.c` |
| `firmware/p3_search.c` |
| `firmware/p3_twin.c` |
| `firmware/bsp/build.sh` |
| `firmware/bsp/lscript.ld` |
| `firmware/bsp/include/bspconfig.h` |
| `firmware/bsp/include/xmem_config.h` |
| `firmware/bsp/include/xparameters.h` |
| `firmware/bsp/src/console.c` |
| `host/gen_firmware_data.py` |
| `tests/test_firmware_twin.py` |
| `tests/test_firmware_audit.py` |
| `fixtures/d1_corpus_v1.json` |
| `host/p3_genome.py` |
| `host/l5_notary.py` |
| `host/l5_refloop.py` |
| `tests/test_p3_genome.py` |
| `tests/test_d1_records.py` |
| `tests/test_sign_genome.py` |
| `tests/test_l5_notary.py` |
| `tests/test_l5_refloop.py` |
| `host/l3_diag_runner.py` |
| `host/l3_diag_jtag.py` |
| `tests/test_l3_diag.py` |
| `evidence/boundary/principal_boundary_2026-08-30-diag.json` |
| `evidence/l3diag_17A6_2026-08-30-02/D_0_read_0x00400a20.json` |
| `evidence/l3diag_17A6_2026-08-30-02/D_0_write_env0.json` |
| `evidence/l3diag_17A6_2026-08-30-02/D_closing_read_0x00400a20.json` |
| `evidence/l3diag_17A6_2026-08-30-02/D_closing_read_0x00400c1a.json` |
| `evidence/l3diag_17A6_2026-08-30-02/D_closing_read_0x00400c20.json` |
| `evidence/l3diag_17A6_2026-08-30-02/diag_verdict.json` |
| `evidence/l3diag_17A6_2026-08-30-02/jtag.json` |
| `evidence/l3diag_17A6_2026-08-30-02/jtag_norecord_1788075428.json` |
| `evidence/l3diag_17A6_2026-08-30-02/jtag_request.json` |
| `evidence/l3diag_17A6_2026-08-30-02/sealed.json` |
| `evidence/l3diag_17A6_2026-08-30-02/summary_pcap.json` |
| `evidence/l3diag_17A6_2026-08-30-02/ymodem.log` |
| `evidence/boundary/principal_boundary_2026-08-30-diag2.json` |
| `evidence/l3diag_17A6_2026-08-30-03/D_0_read_0x00400a20.json` |
| `evidence/l3diag_17A6_2026-08-30-03/D_0_write_env0.json` |
| `evidence/l3diag_17A6_2026-08-30-03/D_1_read_0x00400a20.json` |
| `evidence/l3diag_17A6_2026-08-30-03/D_1_read_0x00400c1a.json` |
| `evidence/l3diag_17A6_2026-08-30-03/D_1_write_env1.json` |
| `evidence/l3diag_17A6_2026-08-30-03/D_2_read_0x00400a20.json` |
| `evidence/l3diag_17A6_2026-08-30-03/D_2_read_0x00400c1a.json` |
| `evidence/l3diag_17A6_2026-08-30-03/D_2_read_0x00400c20.json` |
| `evidence/l3diag_17A6_2026-08-30-03/D_2_write_env2.json` |
| `evidence/l3diag_17A6_2026-08-30-03/diag_verdict.json` |
| `evidence/l3diag_17A6_2026-08-30-03/jtag.json` |
| `evidence/l3diag_17A6_2026-08-30-03/jtag_request.json` |
| `evidence/l3diag_17A6_2026-08-30-03/sealed.json` |
| `evidence/l3diag_17A6_2026-08-30-03/summary_pcap.json` |
| `evidence/l3diag_17A6_2026-08-30-03/ymodem.log` |
| `evidence/boundary/principal_boundary_2026-08-30-l3-03.json` |
| `evidence/l3_17A6_2026-08-30-03/L3_read_0x00400a20.json` |
| `evidence/l3_17A6_2026-08-30-03/L3_read_0x00400a21.json` |
| `evidence/l3_17A6_2026-08-30-03/L3_read_0x00400a22.json` |
| `evidence/l3_17A6_2026-08-30-03/L3_read_0x00400a23.json` |
| `evidence/l3_17A6_2026-08-30-03/L3_read_0x00400c1a.json` |
| `evidence/l3_17A6_2026-08-30-03/L3_read_0x00400c1b.json` |
| `evidence/l3_17A6_2026-08-30-03/L3_read_0x00400c1c.json` |
| `evidence/l3_17A6_2026-08-30-03/L3_read_0x00400c1d.json` |
| `evidence/l3_17A6_2026-08-30-03/L3_read_0x00400c20.json` |
| `evidence/l3_17A6_2026-08-30-03/L3_read_0x00400c21.json` |
| `evidence/l3_17A6_2026-08-30-03/L3_read_0x00400c22.json` |
| `evidence/l3_17A6_2026-08-30-03/L3_read_0x00400c23.json` |
| `evidence/l3_17A6_2026-08-30-03/L3_write_0.json` |
| `evidence/l3_17A6_2026-08-30-03/L3_write_1.json` |
| `evidence/l3_17A6_2026-08-30-03/L3_write_2.json` |
| `evidence/l3_17A6_2026-08-30-03/run_log.json` |
| `evidence/l3_17A6_2026-08-30-03/summary.json` |
| `evidence/l3_17A6_2026-08-30-03/ymodem.log` |
| `evidence/boundary/principal_boundary_2026-08-31-l3-02.json` |
| `evidence/l3_17A6_2026-08-31-01/run_log.json` |
| `evidence/l3_17A6_2026-08-31-01/summary.json` |
| `evidence/l3_17A6_2026-08-31-01/ymodem.log` |
| `evidence/boundary/principal_boundary_2026-08-31-l3-02b.json` |
| `evidence/l3_17A6_2026-08-31-02/L3_read_0x00400a20.json` |
| `evidence/l3_17A6_2026-08-31-02/L3_read_0x00400a21.json` |
| `evidence/l3_17A6_2026-08-31-02/L3_read_0x00400a22.json` |
| `evidence/l3_17A6_2026-08-31-02/L3_read_0x00400a23.json` |
| `evidence/l3_17A6_2026-08-31-02/L3_read_0x00400c1a.json` |
| `evidence/l3_17A6_2026-08-31-02/L3_read_0x00400c1b.json` |
| `evidence/l3_17A6_2026-08-31-02/L3_read_0x00400c1c.json` |
| `evidence/l3_17A6_2026-08-31-02/L3_read_0x00400c1d.json` |
| `evidence/l3_17A6_2026-08-31-02/L3_read_0x00400c20.json` |
| `evidence/l3_17A6_2026-08-31-02/L3_read_0x00400c21.json` |
| `evidence/l3_17A6_2026-08-31-02/L3_read_0x00400c22.json` |
| `evidence/l3_17A6_2026-08-31-02/L3_read_0x00400c23.json` |
| `evidence/l3_17A6_2026-08-31-02/L3_write_0.json` |
| `evidence/l3_17A6_2026-08-31-02/L3_write_1.json` |
| `evidence/l3_17A6_2026-08-31-02/L3_write_2.json` |
| `evidence/l3_17A6_2026-08-31-02/run_log.json` |
| `evidence/l3_17A6_2026-08-31-02/summary.json` |
| `evidence/l3_17A6_2026-08-31-02/ymodem.log` |
| `evidence/boundary/principal_boundary_2026-08-31-l3-03.json` |
| `evidence/l3_17A6_2026-08-31-03/L3_read_0x00400a20.json` |
| `evidence/l3_17A6_2026-08-31-03/L3_read_0x00400a21.json` |
| `evidence/l3_17A6_2026-08-31-03/L3_read_0x00400a22.json` |
| `evidence/l3_17A6_2026-08-31-03/L3_read_0x00400a23.json` |
| `evidence/l3_17A6_2026-08-31-03/L3_read_0x00400c1a.json` |
| `evidence/l3_17A6_2026-08-31-03/L3_read_0x00400c1b.json` |
| `evidence/l3_17A6_2026-08-31-03/L3_read_0x00400c1c.json` |
| `evidence/l3_17A6_2026-08-31-03/L3_read_0x00400c1d.json` |
| `evidence/l3_17A6_2026-08-31-03/L3_read_0x00400c20.json` |
| `evidence/l3_17A6_2026-08-31-03/L3_read_0x00400c21.json` |
| `evidence/l3_17A6_2026-08-31-03/L3_read_0x00400c22.json` |
| `evidence/l3_17A6_2026-08-31-03/L3_read_0x00400c23.json` |
| `evidence/l3_17A6_2026-08-31-03/L3_write_0.json` |
| `evidence/l3_17A6_2026-08-31-03/L3_write_1.json` |
| `evidence/l3_17A6_2026-08-31-03/L3_write_2.json` |
| `evidence/l3_17A6_2026-08-31-03/run_log.json` |
| `evidence/l3_17A6_2026-08-31-03/summary.json` |
| `evidence/l3_17A6_2026-08-31-03/ymodem.log` |
| `evidence/boundary/principal_boundary_2026-08-31-l3-04.json` |
| `evidence/l3_17A6_2026-08-31-04/L3_read_0x00400a20.json` |
| `evidence/l3_17A6_2026-08-31-04/L3_read_0x00400a21.json` |
| `evidence/l3_17A6_2026-08-31-04/L3_read_0x00400a22.json` |
| `evidence/l3_17A6_2026-08-31-04/L3_read_0x00400a23.json` |
| `evidence/l3_17A6_2026-08-31-04/L3_read_0x00400c1a.json` |
| `evidence/l3_17A6_2026-08-31-04/L3_read_0x00400c1b.json` |
| `evidence/l3_17A6_2026-08-31-04/L3_read_0x00400c1c.json` |
| `evidence/l3_17A6_2026-08-31-04/L3_read_0x00400c1d.json` |
| `evidence/l3_17A6_2026-08-31-04/L3_read_0x00400c20.json` |
| `evidence/l3_17A6_2026-08-31-04/L3_read_0x00400c21.json` |
| `evidence/l3_17A6_2026-08-31-04/L3_read_0x00400c22.json` |
| `evidence/l3_17A6_2026-08-31-04/L3_read_0x00400c23.json` |
| `evidence/l3_17A6_2026-08-31-04/L3_write_0.json` |
| `evidence/l3_17A6_2026-08-31-04/L3_write_1.json` |
| `evidence/l3_17A6_2026-08-31-04/L3_write_2.json` |
| `evidence/l3_17A6_2026-08-31-04/run_log.json` |
| `evidence/l3_17A6_2026-08-31-04/summary.json` |
| `evidence/l3_17A6_2026-08-31-04/ymodem.log` |
| `evidence/boundary/principal_boundary_2026-08-31-l3-05.json` |
| `evidence/l3_17A6_2026-08-31-05/L3_read_0x00400a20.json` |
| `evidence/l3_17A6_2026-08-31-05/L3_read_0x00400a21.json` |
| `evidence/l3_17A6_2026-08-31-05/L3_read_0x00400a22.json` |
| `evidence/l3_17A6_2026-08-31-05/L3_read_0x00400a23.json` |
| `evidence/l3_17A6_2026-08-31-05/L3_read_0x00400c1a.json` |
| `evidence/l3_17A6_2026-08-31-05/L3_read_0x00400c1b.json` |
| `evidence/l3_17A6_2026-08-31-05/L3_read_0x00400c1c.json` |
| `evidence/l3_17A6_2026-08-31-05/L3_read_0x00400c1d.json` |
| `evidence/l3_17A6_2026-08-31-05/L3_read_0x00400c20.json` |
| `evidence/l3_17A6_2026-08-31-05/L3_read_0x00400c21.json` |
| `evidence/l3_17A6_2026-08-31-05/L3_read_0x00400c22.json` |
| `evidence/l3_17A6_2026-08-31-05/L3_read_0x00400c23.json` |
| `evidence/l3_17A6_2026-08-31-05/L3_write_0.json` |
| `evidence/l3_17A6_2026-08-31-05/L3_write_1.json` |
| `evidence/l3_17A6_2026-08-31-05/L3_write_2.json` |
| `evidence/l3_17A6_2026-08-31-05/run_log.json` |
| `evidence/l3_17A6_2026-08-31-05/summary.json` |
| `evidence/l3_17A6_2026-08-31-05/ymodem.log` |
| `docs/l4_findings.md` |
| `docs/status.md` |
| `host/run_tests.sh` |
| `evidence/tests/test_report_2026-09-02T175112Z.json` |
| `evidence/tests/test_report_2026-09-02T175035Z.json` |
| `evidence/tests/test_report_2026-09-02T172002Z.json` |
| `evidence/tests/test_report_2026-09-02T171913Z.json` |
| `evidence/tests/test_report_2026-09-02T085755Z.json` |
| `evidence/tests/test_report_2026-09-02T084241Z.json` |
| `evidence/tests/test_report_2026-09-02T084227Z.json` |
| `evidence/tests/test_report_2026-09-02T081019Z.json` |
| `evidence/tests/test_report_2026-09-02T054002Z.json` |
| `evidence/tests/test_report_2026-09-02T053951Z.json` |
| `evidence/tests/test_report_2026-09-02T053909Z.json` |
| `evidence/tests/test_report_2026-09-02T053858Z.json` |
| `evidence/tests/test_report_2026-09-02T052126Z.json` |
| `evidence/tests/test_report_2026-09-02T052115Z.json` |
| `evidence/tests/test_report_2026-09-01T202516Z.json` |
| `evidence/tests/test_report_2026-09-01T201128Z.json` |
| `evidence/tests/test_report_2026-09-01T200750Z.json` |
| `evidence/tests/test_report_2026-09-01T195838Z.json` |
| `evidence/tests/test_report_2026-09-01T195210Z.json` |
| `evidence/tests/test_report_2026-09-01T193440Z.json` |
| `evidence/tests/test_report_2026-09-01T193428Z.json` |
| `evidence/tests/test_report_2026-09-01T192752Z.json` |
| `evidence/tests/test_report_2026-09-01T192741Z.json` |
| `evidence/tests/test_report_2026-09-01T192627Z.json` |
| `evidence/tests/test_report_2026-09-01T191907Z.json` |
| `evidence/tests/test_report_2026-09-01T191858Z.json` |
| `evidence/tests/test_report_2026-09-01T191135Z.json` |
| `evidence/tests/test_report_2026-09-01T191126Z.json` |
| `evidence/tests/test_report_2026-09-01T184834Z.json` |
| `evidence/tests/test_report_2026-09-01T184824Z.json` |
| `evidence/tests/test_report_2026-09-01T182129Z.json` |
| `evidence/tests/test_report_2026-09-01T181507Z.json` |
| `evidence/tests/test_report_2026-09-01T180634Z.json` |
| `evidence/tests/test_report_2026-09-01T175438Z.json` |
| `evidence/tests/test_report_2026-09-01T175024Z.json` |
| `evidence/tests/test_report_2026-09-01T173855Z.json` |
| `evidence/tests/test_report_2026-09-01T173417Z.json` |
| `evidence/tests/test_report_2026-09-01T173339Z.json` |
| `evidence/tests/test_report_2026-09-01T173247Z.json` |
| `evidence/tests/test_report_2026-09-01T172412Z.json` |
| `evidence/tests/test_report_2026-09-01T172330Z.json` |
| `evidence/tests/test_report_2026-09-01T172234Z.json` |
| `evidence/tests/test_report_2026-09-01T140316Z.json` |
| `evidence/tests/test_report_2026-09-01T140129Z.json` |
| `evidence/tests/test_report_2026-09-01T134106Z.json` |
| `evidence/tests/test_report_2026-09-01T134039Z.json` |
| `evidence/tests/test_report_2026-09-01T132756Z.json` |
| `evidence/tests/test_report_2026-09-01T132048Z.json` |
| `evidence/tests/test_report_2026-09-01T132037Z.json` |
| `evidence/tests/test_report_2026-09-01T131928Z.json` |
| `evidence/tests/test_report_2026-09-01T130914Z.json` |
| `evidence/tests/test_report_2026-09-01T112600Z.json` |
| `evidence/tests/test_report_2026-09-01T111154Z.json` |
| `evidence/tests/test_report_2026-09-01T110537Z.json` |
| `evidence/tests/test_report_2026-09-01T110028Z.json` |
| `evidence/tests/test_report_2026-09-01T105945Z.json` |
| `evidence/tests/test_report_2026-09-01T105021Z.json` |
| `evidence/tests/test_report_2026-09-01T104810Z.json` |
| `evidence/tests/test_report_2026-09-01T102513Z.json` |
| `evidence/tests/test_report_2026-09-01T102029Z.json` |
| `evidence/tests/test_report_2026-09-01T100112Z.json` |
| `evidence/tests/test_report_2026-09-01T095451Z.json` |
| `evidence/tests/test_report_2026-09-01T095337Z.json` |
| `evidence/tests/test_report_2026-09-01T094951Z.json` |
| `evidence/tests/test_report_2026-09-01T093833Z.json` |
| `evidence/tests/test_report_2026-09-01T093330Z.json` |
| `evidence/tests/test_report_2026-09-01T093157Z.json` |
| `evidence/tests/test_report_2026-09-01T092623Z.json` |
| `evidence/tests/test_report_2026-09-01T092133Z.json` |
| `evidence/tests/test_report_2026-09-01T090809Z.json` |
| `evidence/tests/test_report_2026-09-01T085031Z.json` |
| `evidence/tests/test_report_2026-09-01T083156Z.json` |
| `evidence/tests/test_report_2026-09-01T082319Z.json` |
| `evidence/tests/test_report_2026-09-01T080322Z.json` |
| `evidence/tests/test_report_2026-09-01T075330Z.json` |
| `evidence/tests/test_report_2026-09-01T074518Z.json` |
| `evidence/tests/test_report_2026-09-01T071959Z.json` |
| `evidence/tests/test_report_2026-09-01T071516Z.json` |
| `evidence/tests/test_report_2026-08-31T192905Z.json` |
| `evidence/tests/test_report_2026-08-31T190537Z.json` |
| `evidence/tests/test_report_2026-08-31T182343Z.json` |
| `evidence/tests/test_report_2026-08-31T180341Z.json` |
| `evidence/tests/test_report_2026-08-31T180156Z.json` |
| `evidence/tests/test_report_2026-08-31T173214Z.json` |
| `evidence/tests/test_report_2026-08-31T170013Z.json` |
| `evidence/tests/test_report_2026-08-31T165925Z.json` |
| `evidence/tests/test_report_2026-08-31T165818Z.json` |
| `evidence/tests/test_report_2026-08-31T163325Z.json` |
| `evidence/tests/test_report_2026-08-31T161111Z.json` |
| `evidence/tests/test_report_2026-08-31T155428Z.json` |
| `evidence/tests/test_report_2026-08-31T155401Z.json` |
| `evidence/tests/test_report_2026-08-31T153507Z.json` |
| `evidence/tests/test_report_2026-08-31T153501Z.json` |
| `evidence/tests/test_report_2026-08-31T153424Z.json` |
| `host/test_report.py` |
| `tests/test_test_report.py` |
| `evidence/tests/test_report_2026-08-31T153009Z.json` |
| `evidence/tests/test_report_2026-08-31T152940Z.json` |
| `evidence/tests/test_report_2026-08-31T152909Z.json` |
| `evidence/boundary/principal_boundary_2026-08-31-l4.json` |
| `evidence/l4_17A6_2026-08-31-06/L4_0_gate_refused.json` |
| `evidence/l4_17A6_2026-08-31-06/L4_1_corrupt_stage.json` |
| `evidence/l4_17A6_2026-08-31-06/L4_2_restore_write_0.json` |
| `evidence/l4_17A6_2026-08-31-06/L4_2_restore_write_1.json` |
| `evidence/l4_17A6_2026-08-31-06/L4_2_restore_write_2.json` |
| `evidence/l4_17A6_2026-08-31-06/L4_3_restore_read_0x00400a20.json` |
| `evidence/l4_17A6_2026-08-31-06/L4_3_restore_read_0x00400a21.json` |
| `evidence/l4_17A6_2026-08-31-06/L4_3_restore_read_0x00400a22.json` |
| `evidence/l4_17A6_2026-08-31-06/L4_3_restore_read_0x00400a23.json` |
| `evidence/l4_17A6_2026-08-31-06/L4_3_restore_read_0x00400c1a.json` |
| `evidence/l4_17A6_2026-08-31-06/L4_3_restore_read_0x00400c1b.json` |
| `evidence/l4_17A6_2026-08-31-06/L4_3_restore_read_0x00400c1c.json` |
| `evidence/l4_17A6_2026-08-31-06/L4_3_restore_read_0x00400c1d.json` |
| `evidence/l4_17A6_2026-08-31-06/L4_3_restore_read_0x00400c20.json` |
| `evidence/l4_17A6_2026-08-31-06/L4_3_restore_read_0x00400c21.json` |
| `evidence/l4_17A6_2026-08-31-06/L4_3_restore_read_0x00400c22.json` |
| `evidence/l4_17A6_2026-08-31-06/L4_3_restore_read_0x00400c23.json` |
| `evidence/l4_17A6_2026-08-31-06/run_log.json` |
| `evidence/l4_17A6_2026-08-31-06/summary.json` |
| `evidence/l4_17A6_2026-08-31-06/ymodem.log` |
| `evidence/l2_17A6_2026-08-29-01/L2_0_fclk.json` |
| `evidence/l2_17A6_2026-08-29-01/L2_1_baseline.json` |
| `evidence/l2_17A6_2026-08-29-01/L2_2_control.json` |
| `evidence/l2_17A6_2026-08-29-01/L2_3_read_0.json` |
| `evidence/l2_17A6_2026-08-29-01/L2_3_read_1.json` |
| `evidence/l2_17A6_2026-08-29-01/L2_3_read_2.json` |
| `evidence/l2_17A6_2026-08-29-01/L2_3_read_3.json` |
| `evidence/l2_17A6_2026-08-29-01/L2_3_read_4.json` |
| `evidence/l2_17A6_2026-08-29-01/L2_3_read_5.json` |
| `evidence/l2_17A6_2026-08-29-01/L2_3_read_6.json` |
| `evidence/l2_17A6_2026-08-29-01/L2_3_read_7.json` |
| `evidence/l2_17A6_2026-08-29-01/L2_3_read_8.json` |
| `evidence/l2_17A6_2026-08-29-01/L2_3_read_9.json` |
| `host/gen_bsp_input_manifest.py` |
| `host/gen_build_evidence.py` |
| `manifests/l5_bsp_inputs.json` |
| `tests/test_bsp_inputs_manifest.py` |
| `docs/l5_review_result.md` |
| `evidence/l5_build/build_evidence.json` |
| `evidence/l5_build/p3_app.map` |
| `firmware/p3_wire.c` |
| `firmware/p3_wire.h` |
| `firmware/p3_wire_twin.c` |
| `tests/test_firmware_wire_contract.py` |
| `host/l5_runner.py` |
| `tests/test_l5_runner.py` |
| `docs/l5_wire_findings.md` |
| `docs/l5_session1_findings.md` |
| `docs/l5_diag_spec.md` |
| `docs/l5_session2_findings.md` |
| `tests/test_axi_map_vs_rtl.py` |
| `evidence/boundary/principal_boundary_2026-09-01-04.json` |
| `evidence/l5_17A6_2026-09-01-04/L5_0_preflight.json` |
| `evidence/l5_17A6_2026-09-01-04/L5_1_identity_page.json` |
| `evidence/l5_17A6_2026-09-01-04/audits.json` |
| `evidence/l5_17A6_2026-09-01-04/console.log` |
| `evidence/l5_17A6_2026-09-01-04/run_log.json` |
| `evidence/l5_17A6_2026-09-01-04/summary.json` |
| `evidence/l5_17A6_2026-09-01-04/ymodem.log` |
| `evidence/l5_17A6_2026-09-01-04/ymodem_app.log` |
| `docs/l5_session4_findings.md` |
| `docs/l6_soak_prereg.md` |
| `host/l6_schedule.py` |
| `host/l6_operators.py` |
| `host/l6_timing.py` |
| `host/l6_rate.py` |
| `host/l6_checks.py` |
| `host/l6_runner.py` |
| `fixtures/l6_operator_corpus_v1.json` |
| `manifests/l6_manifest.json` |
| `docs/l6_instrument.md` |
| `tests/test_l6_schedule.py` |
| `tests/test_l6_operators.py` |
| `tests/test_l6_timing.py` |
| `tests/test_l6_rate.py` |
| `tests/test_l6_policy.py` |
| `tests/test_l6_runner.py` |
| `docs/l6_compat_review_package.md` |
| `manifests/l6_bsp_inputs.json` |
| `evidence/l6_build/build_evidence.json` |
| `evidence/l6_build/p3_app_l6.map` |
| `evidence/l6_build/build_evidence_bd1454cd.json` |
| `evidence/l6_build/p3_app_l6_bd1454cd.map` |
| `docs/l6_c1_session1_findings.md` |
| `host/l6_reader.py` |
| `tests/test_l6_reader.py` |
| `docs/l6_c1_session2_findings.md` |
| `docs/l6_c1_session3_findings.md` |
| `host/l6_console.py` |
| `tests/test_l6_console.py` |
| `host/l6_loss_stats.py` |
| `evidence/l6_console_loss_stats.json` |
| `docs/l6_console_loss_summary.md` |
| `host/l6_audit_pull.py` |
| `tests/test_l6_audit_pull.py` |
| `docs/l6_audit_pull_design.md` |
| `tests/test_l6_sparse.py` |
| `docs/l6_pull_batch_package.md` |
| `docs/l6_soak_prereg_v0.3_draft.md` |
| `evidence/l6_next_build/build_evidence.json` |
| `evidence/l6_next_build/p3_app_l6.map` |
| `evidence/boundary/principal_boundary_2026-09-01-08.json` |
| `evidence/l6_17A6_2026-09-01-08-C1/L6_0_preflight.json` |
| `evidence/l6_17A6_2026-09-01-08-C1/L6_1_identity_page.json` |
| `evidence/l6_17A6_2026-09-01-08-C1/audits.json` |
| `evidence/l6_17A6_2026-09-01-08-C1/console.log` |
| `evidence/l6_17A6_2026-09-01-08-C1/console.ts.log` |
| `evidence/l6_17A6_2026-09-01-08-C1/run_log.json` |
| `evidence/l6_17A6_2026-09-01-08-C1/summary.json` |
| `evidence/l6_17A6_2026-09-01-08-C1/timeline.json` |
| `evidence/l6_17A6_2026-09-01-08-C1/ymodem.log` |
| `evidence/l6_17A6_2026-09-01-08-C1/ymodem_app.log` |
| `docs/l6_c1_session4_findings.md` |
| `evidence/boundary/principal_boundary_2026-09-01-09.json` |
| `evidence/l6_17A6_2026-09-01-09-C1/L6_0_preflight.json` |
| `evidence/l6_17A6_2026-09-01-09-C1/L6_1_identity_page.json` |
| `evidence/l6_17A6_2026-09-01-09-C1/audits.json` |
| `evidence/l6_17A6_2026-09-01-09-C1/console.log` |
| `evidence/l6_17A6_2026-09-01-09-C1/console.ts.log` |
| `evidence/l6_17A6_2026-09-01-09-C1/rate_report.json` |
| `evidence/l6_17A6_2026-09-01-09-C1/run_log.json` |
| `evidence/l6_17A6_2026-09-01-09-C1/summary.json` |
| `evidence/l6_17A6_2026-09-01-09-C1/timeline.json` |
| `evidence/l6_17A6_2026-09-01-09-C1/ymodem.log` |
| `evidence/l6_17A6_2026-09-01-09-C1/ymodem_app.log` |
| `docs/l6_c2_session1_findings.md` |
| `evidence/boundary/principal_boundary_2026-09-01-10.json` |
| `evidence/l6_17A6_2026-09-01-10-C2/L6_0_preflight.json` |
| `evidence/l6_17A6_2026-09-01-10-C2/L6_1_identity_page.json` |
| `evidence/l6_17A6_2026-09-01-10-C2/audits.json` |
| `evidence/l6_17A6_2026-09-01-10-C2/console.log` |
| `evidence/l6_17A6_2026-09-01-10-C2/console.ts.log` |
| `evidence/l6_17A6_2026-09-01-10-C2/rate_report.json` |
| `evidence/l6_17A6_2026-09-01-10-C2/run_log.json` |
| `evidence/l6_17A6_2026-09-01-10-C2/summary.json` |
| `evidence/l6_17A6_2026-09-01-10-C2/timeline.json` |
| `evidence/l6_17A6_2026-09-01-10-C2/ymodem.log` |
| `evidence/l6_17A6_2026-09-01-10-C2/ymodem_app.log` |
| `docs/l6_s_session1_findings.md` |
| `evidence/boundary/principal_boundary_2026-09-01-11.json` |
| `evidence/l6_17A6_2026-09-01-11-S/L6_0_preflight.json` |
| `evidence/l6_17A6_2026-09-01-11-S/L6_1_identity_page.json` |
| `evidence/l6_17A6_2026-09-01-11-S/audits.json` |
| `evidence/l6_17A6_2026-09-01-11-S/console.log` |
| `evidence/l6_17A6_2026-09-01-11-S/console.ts.log` |
| `evidence/l6_17A6_2026-09-01-11-S/run_log.json` |
| `evidence/l6_17A6_2026-09-01-11-S/summary.json` |
| `evidence/l6_17A6_2026-09-01-11-S/timeline.json` |
| `evidence/l6_17A6_2026-09-01-11-S/ymodem.log` |
| `evidence/l6_17A6_2026-09-01-11-S/ymodem_app.log` |
| `docs/l6_c1_session5_findings.md` |
| `evidence/boundary/principal_boundary_2026-09-02-01.json` |
| `evidence/l6_17A6_2026-09-02-01-C1/L6_0_preflight.json` |
| `evidence/l6_17A6_2026-09-02-01-C1/L6_1_identity_page.json` |
| `evidence/l6_17A6_2026-09-02-01-C1/audits.json` |
| `evidence/l6_17A6_2026-09-02-01-C1/console.log` |
| `evidence/l6_17A6_2026-09-02-01-C1/console.ts.log` |
| `evidence/l6_17A6_2026-09-02-01-C1/rate_report.json` |
| `evidence/l6_17A6_2026-09-02-01-C1/run_log.json` |
| `evidence/l6_17A6_2026-09-02-01-C1/summary.json` |
| `evidence/l6_17A6_2026-09-02-01-C1/timeline.json` |
| `evidence/l6_17A6_2026-09-02-01-C1/ymodem.log` |
| `evidence/l6_17A6_2026-09-02-01-C1/ymodem_app.log` |
| `docs/l6_transport_batch_package.md` |
| `docs/l6_soak_prereg_v0.5_draft.md` |
| `host/l6_transport_soak.py` |
| `tests/test_l6_transport.py` |
| `evidence/l6_transport_soak/soak_noresync_heavy.json` |
| `evidence/l6_transport_soak/soak_resync_base.json` |
| `evidence/l6_transport_soak/soak_resync_heavy.json` |
| `evidence/l6_transport_soak/soak_resync_t05.json` |
| `evidence/l6_transport_soak/soak_resync_t05_heavy.json` |
| `host/l6_rec.py` |
| `tests/test_l6_rec.py` |
| `tests/test_l6_crash_summary.py` |
| `firmware/p3_rectx.c` |
| `firmware/p3_rectx.h` |
| `docs/l6_rec_transaction_design.md` |
| `docs/l6_soak_prereg_v0.4_draft.md` |
| `docs/l6_rec_batch_package.md` |
| `evidence/l6_next_build/build_evidence_e19e1b12.json` |
| `evidence/l6_next_build/p3_app_l6_e19e1b12.map` |
| `evidence/l6_next_build/build_evidence_cd8360dc.json` |
| `evidence/l6_next_build/p3_app_l6_cd8360dc.map` |
| `evidence/l6_build/build_evidence_e19e1b12.json` |
| `evidence/l6_build/p3_app_l6_e19e1b12.map` |
| `evidence/boundary/principal_boundary_2026-09-01-07.json` |
| `evidence/l6_17A6_2026-09-01-07-C1/L6_0_preflight.json` |
| `evidence/l6_17A6_2026-09-01-07-C1/L6_1_identity_page.json` |
| `evidence/l6_17A6_2026-09-01-07-C1/audits.json` |
| `evidence/l6_17A6_2026-09-01-07-C1/console.log` |
| `evidence/l6_17A6_2026-09-01-07-C1/console.ts.log` |
| `evidence/l6_17A6_2026-09-01-07-C1/run_log.json` |
| `evidence/l6_17A6_2026-09-01-07-C1/summary.json` |
| `evidence/l6_17A6_2026-09-01-07-C1/timeline.json` |
| `evidence/l6_17A6_2026-09-01-07-C1/ymodem.log` |
| `evidence/l6_17A6_2026-09-01-07-C1/ymodem_app.log` |
| `evidence/boundary/principal_boundary_2026-09-01-06.json` |
| `evidence/l6_17A6_2026-09-01-06-C1/L6_0_preflight.json` |
| `evidence/l6_17A6_2026-09-01-06-C1/L6_1_identity_page.json` |
| `evidence/l6_17A6_2026-09-01-06-C1/audits.json` |
| `evidence/l6_17A6_2026-09-01-06-C1/console.log` |
| `evidence/l6_17A6_2026-09-01-06-C1/console.ts.log` |
| `evidence/l6_17A6_2026-09-01-06-C1/run_log.json` |
| `evidence/l6_17A6_2026-09-01-06-C1/summary.json` |
| `evidence/l6_17A6_2026-09-01-06-C1/timeline.json` |
| `evidence/l6_17A6_2026-09-01-06-C1/ymodem.log` |
| `evidence/l6_17A6_2026-09-01-06-C1/ymodem_app.log` |
| `host/slcr_read.py` |
| `evidence/preflight/slcr_17A6_2026-09-01-05.json` |
| `evidence/boundary/principal_boundary_2026-09-01-03.json` |
| `evidence/l5_17A6_2026-09-01-03/L5_0_preflight.json` |
| `evidence/l5_17A6_2026-09-01-03/L5_1_identity_page.json` |
| `evidence/l5_17A6_2026-09-01-03/audits.json` |
| `evidence/l5_17A6_2026-09-01-03/console.log` |
| `evidence/l5_17A6_2026-09-01-03/run_log.json` |
| `evidence/l5_17A6_2026-09-01-03/summary.json` |
| `evidence/l5_17A6_2026-09-01-03/ymodem.log` |
| `evidence/l5_17A6_2026-09-01-03/ymodem_app.log` |
| `docs/l5_session3_findings.md` |
| `docs/l5_settle_correction.md` |
| `docs/l5_session4_spec.md` |
| `validators/audit.py` |
| `tests/test_audit_gate.py` |
| `evidence/boundary/principal_boundary_2026-09-01-02.json` |
| `evidence/l5_17A6_2026-09-01-02/L5_0_preflight.json` |
| `evidence/l5_17A6_2026-09-01-02/L5_1_identity_page.json` |
| `evidence/l5_17A6_2026-09-01-02/audits.json` |
| `evidence/l5_17A6_2026-09-01-02/console.log` |
| `evidence/l5_17A6_2026-09-01-02/run_log.json` |
| `evidence/l5_17A6_2026-09-01-02/summary.json` |
| `evidence/l5_17A6_2026-09-01-02/ymodem.log` |
| `evidence/l5_17A6_2026-09-01-02/ymodem_app.log` |
| `evidence/boundary/principal_boundary_2026-09-01.json` |
| `evidence/l5_17A6_2026-09-01-01/L5_0_preflight.json` |
| `evidence/l5_17A6_2026-09-01-01/L5_1_identity_page.json` |
| `evidence/l5_17A6_2026-09-01-01/audits.json` |
| `evidence/l5_17A6_2026-09-01-01/console.log` |
| `evidence/l5_17A6_2026-09-01-01/run_log.json` |
| `evidence/l5_17A6_2026-09-01-01/summary.json` |
| `evidence/l5_17A6_2026-09-01-01/ymodem.log` |
| `evidence/l5_17A6_2026-09-01-01/ymodem_app.log` |
| `tests/test_package_consistency.py` |
| `docs/l5_post_build_package.md` |

## Deliberately NOT imported

| file | why |
|---|---|
| `zynq-fabricmap/scripts/gate_board_identity.py`, `board_uboot_axi.py`, `board_carrier_guard.py`, `board_carrier_exec.py`, `board_uboot_fpga_load.py`, `precheck_fresh_power.py` | the carrier-era authority and ICAPE2 write path; P3 has no ICAP writer and takes its session from `zynq-psmap` |
| `zynq-fabricmap/vivado/carrier/carrier_stream.v`, `carrier_crc32.v`, `icape2_model.v`, `carrier_top.v` | the ICAPE2 stream engine and its model — the part of the carrier P3 removes |
| any `evidence/` of either repository | evidence stays where it was produced; P3 cites it by commit |
| Xilinx `embeddedsw` BSP sources (`standalone_v9_4`, `scuwdt_v2_6`) used to build the L5 image | third-party vendor sources under a separate licence, referenced **in place** by `firmware/bsp/build.sh` at `/home/test/Xilinx/2025.2/data/embeddedsw`, not vendored here. Only the glue original to this repo (`firmware/bsp/`) is tracked. **These files are now pinned by sha256** in `manifests/l5_bsp_inputs.json` (path/size/sha256 for every source + header the build reads), so `app_image_sha256` reproduces against that *identified* input set plus the sha-pinned xPack toolchain. Not vendored (licence review pending) means the repo still needs the 2025.2 tree present to rebuild — see `docs/l5_findings.md` §6 |
