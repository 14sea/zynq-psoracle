#!/usr/bin/env bash
# Host-only simulation of the P3 carrier logic (iverilog). Exit status = pass/fail.
set -u
cd "$(dirname "$0")/.."
G=imported/fabricmap/vivado/carrier/generated
python3 tb/gen_siphash_vectors.py >/dev/null && python3 tb/gen_arm_fixture.py >/dev/null || exit 1
mkdir -p sim/out
iverilog -g2012 -o sim/out/siphash.vvp rtl/p3_siphash.v tb/tb_p3_siphash.v || exit 1
iverilog -g2012 -I tb -I $G -o sim/out/core.vvp rtl/p3_siphash.v rtl/p3_arm_gate.v rtl/p3_axil.v rtl/p3_core.v \
    imported/fabricmap/vivado/carrier/carrier_scorer.v tb/tb_p3_core.v || exit 1
rc=0
r1=$(vvp -N sim/out/siphash.vvp | grep -E '^TB_'); echo "tb_p3_siphash: $r1"; [ "$r1" = TB_PASS ] || rc=1
r2=$(cd $G && vvp -N ../../../../../sim/out/core.vvp | grep -E '^TB_'); echo "tb_p3_core:    $r2"; [ "$r2" = TB_PASS ] || rc=1
exit $rc
