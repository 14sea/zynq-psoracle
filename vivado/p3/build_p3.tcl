# P3 carrier build: synth -> pblock -> place/route -> isolation checks -> bitstream -> provenance.
# Usage: vivado -mode batch -source build_p3.tcl -tclargs <outdir> <NONCE_SEED as 16 hex>
# There is no key generic: the MAC key is provisioned at runtime into a write-once register
# (docs/decisions.md D4, option A), so the bitstream is public and reproducible.
set outdir [lindex $argv 0]
set seedhex [lindex $argv 1]
set part   xc7z010clg400-1
set here   [file dirname [file normalize [info script]]]
set repo   [file dirname [file dirname $here]]
set fm     $repo/imported/fabricmap/vivado/carrier
file mkdir $outdir
create_project -in_memory -part $part
set srcs [list $repo/rtl/p3_top.v $repo/rtl/p3_core.v $repo/rtl/p3_axil.v $repo/rtl/p3_arm_gate.v \
               $repo/rtl/p3_siphash.v $fm/carrier_axi3_lite.v $fm/carrier_scorer.v]
add_files -norecurse $srcs
set_property include_dirs [list $fm/generated] [current_fileset]
add_files -fileset constrs_1 -norecurse $fm/carrier.xdc
synth_design -top p3_top -part $part -flatten_hierarchy none -include_dirs $fm/generated \
    -generic "NONCE_SEED=64'h$seedhex"
write_checkpoint -force $outdir/post_synth.dcp
report_utilization -file $outdir/post_synth_util.rpt
opt_design
# the logic pblock: the carrier's two slice-column pairs plus columns far from the target and
# flush tiles; the isolation checks below, not this list, decide whether isolation held.
create_pblock pb_logic
set logic_cells [get_cells -hierarchical -filter {IS_PRIMITIVE && NAME !~ "evolvable_*"}]
if {[llength $logic_cells] < 100} { error "pblock would capture only [llength $logic_cells] cells" }
add_cells_to_pblock pb_logic $logic_cells
resize_pblock pb_logic -add {SLICE_X0Y0:SLICE_X1Y99}
resize_pblock pb_logic -add {SLICE_X6Y0:SLICE_X7Y99}
resize_pblock pb_logic -add {SLICE_X14Y0:SLICE_X25Y99}
set_property IS_SOFT false [get_pblocks pb_logic]
puts "pblock pb_logic: PRIMITIVE_COUNT=[get_property PRIMITIVE_COUNT [get_pblocks pb_logic]]"
place_design
route_design
write_checkpoint -force $outdir/post_route.dcp
report_timing_summary -file $outdir/timing.rpt
report_utilization   -file $outdir/post_route_util.rpt
source $fm/isolation_checks.tcl
carrier_isolation_checks $outdir
write_bitstream -force $outdir/p3.bit
set bit_sha [lindex [exec sha256sum $outdir/p3.bit] 0]
set wns [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]]
set fh [open $outdir/p3_build.json w]
puts $fh "{\"schema\": \"p3_build\", \"schema_version\": \"1.0.0\", \"part\": \"$part\", \"top\": \"p3_top\","
puts $fh " \"vivado\": \"[version -short]\", \"routed\": true, \"cell_isolation\": \"passed\", \"wns_ns\": $wns,"
puts $fh " \"bitstream\": \"p3.bit\", \"bitstream_sha256\": \"$bit_sha\", \"nonce_seed\": \"0x$seedhex\","
puts $fh " \"key\": \"runtime-provisioned, write-once register (docs/decisions.md D4 option A); not in this bitstream\"}"
close $fh
puts "P3 BUILD OK -> $outdir/p3.bit ($bit_sha) WNS=$wns"
