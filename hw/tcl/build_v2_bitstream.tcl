# Synthesize, implement, report, and export the V2 project.
set jobs [expr {$argc > 0 ? [lindex $argv 0] : 8}]
set script_dir [file normalize [file dirname [info script]]]
set root_dir [file normalize [file join $script_dir ../..]]
set build_dir [file normalize [file join $root_dir build vivado trigger_v2]]
set project_name kr260_trigger_v2
set xpr [file join $build_dir ${project_name}.xpr]
if {![file exists $xpr]} { error "V2 project does not exist: $xpr" }
open_project $xpr

reset_run synth_1
launch_runs synth_1 -jobs $jobs
wait_on_run synth_1
set synth_status [get_property STATUS [get_runs synth_1]]
if {[string first "Complete" $synth_status] < 0} {
    error "V2 synthesis failed: $synth_status"
}

set_property STEPS.WRITE_BITSTREAM.ARGS.BIN_FILE true [get_runs impl_1]
launch_runs impl_1 -to_step write_bitstream -jobs $jobs
wait_on_run impl_1
set impl_status [get_property STATUS [get_runs impl_1]]
if {[string first "Complete" $impl_status] < 0} {
    error "V2 implementation/bitstream failed: $impl_status"
}

open_run impl_1
file mkdir [file join $root_dir reports]
report_timing_summary -delay_type min_max -max_paths 20 -report_unconstrained \
    -file [file join $root_dir reports trigger_v2_timing_summary.rpt]
report_utilization -hierarchical \
    -file [file join $root_dir reports trigger_v2_utilization.rpt]
report_drc -file [file join $root_dir reports trigger_v2_drc.rpt]
write_hw_platform -fixed -include_bit -force \
    -file [file join $build_dir ${project_name}.xsa]

set run_dir [get_property DIRECTORY [get_runs impl_1]]
set bit_file [file join $run_dir system_wrapper.bit]
set bin_file [file join $run_dir system_wrapper.bin]
if {![file exists $bit_file]} { error "expected V2 bitstream not found: $bit_file" }
file mkdir [file join $root_dir deploy]
file copy -force $bit_file [file join $root_dir deploy ${project_name}.bit]
if {[file exists $bin_file]} {
    file copy -force $bin_file [file join $root_dir deploy ${project_name}.bin]
}
set hwh_file [file join $build_dir ${project_name}.gen sources_1 bd system hw_handoff system.hwh]
if {![file exists $hwh_file]} { error "expected V2 hardware handoff not found: $hwh_file" }
file copy -force $hwh_file [file join $root_dir deploy ${project_name}.hwh]

set summary [open [file join $root_dir reports trigger_v2_build_summary.txt] w]
puts $summary "mode=trigger_v2"
puts $summary "vivado=[version -short]"
puts $summary "part=[get_property PART [current_project]]"
puts $summary "board_part=[get_property BOARD_PART [current_project]]"
puts $summary "synthesis_status=$synth_status"
puts $summary "implementation_status=$impl_status"
puts $summary "items=22"
puts $summary "input_words_per_event=11"
puts $summary "input_beat_initiation_interval_cycles=1"
puts $summary "event_initiation_interval_cycles=11"
puts $summary "result_latency_from_final_beat_cycles=1"
close $summary
close_project
