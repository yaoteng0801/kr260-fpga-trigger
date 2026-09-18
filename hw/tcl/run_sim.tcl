set script_dir [file normalize [file dirname [info script]]]
set root_dir [file normalize [file join $script_dir ../..]]
set sim_dir [file normalize [file join $root_dir build sim]]
file delete -force $sim_dir

proc run_testbench {root_dir sim_dir project_name rtl_files tb_file top_name} {
    set project_dir [file join $sim_dir $project_name]
    create_project $project_name $project_dir -part xck26-sfvc784-2LV-c -force
    add_files -norecurse $rtl_files
    add_files -fileset sim_1 -norecurse $tb_file
    set_property top $top_name [get_filesets sim_1]
    set_property target_simulator XSim [current_project]
    update_compile_order -fileset sim_1
    # Vivado's in-process simulator feature can be affected by unrelated host
    # Tcl/Python packages. Generate the official XSim scripts, then execute
    # compile/elaborate/simulate as child processes in Vivado's own tool
    # environment. This is equivalent to the GUI flow and is more reproducible.
    launch_simulation -scripts_only
    set xsim_dir [file join $project_dir ${project_name}.sim sim_1 behav xsim]
    foreach step {compile.sh elaborate.sh simulate.sh} {
        set command [file join $xsim_dir $step]
        if {[catch {exec bash $command 2>@1} output options]} {
            puts $output
            return -options $options "XSim $step failed"
        }
        puts $output
    }
    close_project
}

run_testbench $root_dir $sim_dir core_sim \
    [list [file join $root_dir hw rtl axis_trigger_core.sv]] \
    [file join $root_dir hw tb tb_axis_trigger_core.sv] \
    tb_axis_trigger_core

run_testbench $root_dir $sim_dir regs_sim \
    [list [file join $root_dir hw rtl trigger_axi_lite_regs.sv]] \
    [file join $root_dir hw tb tb_trigger_axi_lite_regs.sv] \
    tb_trigger_axi_lite_regs
