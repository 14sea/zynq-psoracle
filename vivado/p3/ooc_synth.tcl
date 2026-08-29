# Out-of-context synthesis of p3_core (everything below PS7/shim) for the resource/timing
# gate. Host-only. Usage: vivado -mode batch -source ooc_synth.tcl -tclargs <outdir>
set outdir [lindex $argv 0]
set part   xc7z010clg400-1
set here   [file dirname [file normalize [info script]]]
set repo   [file dirname [file dirname $here]]
set fm     $repo/imported/fabricmap/vivado/carrier
file mkdir $outdir
create_project -in_memory -part $part
set srcs [list $repo/rtl/p3_siphash.v $repo/rtl/p3_arm_gate.v $repo/rtl/p3_axil.v $repo/rtl/p3_core.v $fm/carrier_scorer.v]
add_files -norecurse $srcs
set_property include_dirs [list $fm/generated] [current_fileset]
# a representative key/seed so the constant-propagation of K is what the real build sees
synth_design -top p3_core -part $part -mode out_of_context -flatten_hierarchy none \
    -include_dirs $fm/generated \
    -generic {KEY=128'h0f0e0d0c0b0a09080706050403020100} -generic {NONCE_SEED=64'h9E3779B97F4A7C15}
create_clock -period 20.000 -name clk [get_ports clk]
report_utilization -file $outdir/ooc_util.rpt
report_timing_summary -file $outdir/ooc_timing.rpt
set wns [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]]
puts "OOC_WNS $wns"
write_checkpoint -force $outdir/p3_core_ooc.dcp
puts "OOC_DONE"
