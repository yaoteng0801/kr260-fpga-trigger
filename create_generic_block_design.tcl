set script_dir [file normalize [file dirname [info script]]]
set project_file [file join $script_dir kr260_self_driving_trigger.xpr]
set design_name design_1

open_project $project_file

set existing_bd [get_files -quiet */${design_name}.bd]
if {[llength $existing_bd] != 0} {
    open_bd_design $existing_bd
    delete_bd_objs [get_bd_cells]
} else {
    create_bd_design $design_name
    current_bd_design $design_name
}

set ps [create_bd_cell -type ip \
    -vlnv xilinx.com:ip:zynq_ultra_ps_e:* zynq_ultra_ps_e_0]

# Load the DDR, clocks, fixed I/O, and processing-system settings supplied by
# the KR260 SOM board definition.
apply_bd_automation -rule xilinx.com:bd_rule:zynq_ultra_ps_e \
    -config {apply_board_preset "1"} $ps

# The preset enables the two PS-to-PL AXI masters. Clock them from the default
# 100 MHz PL clock so the otherwise generic design is structurally complete.
connect_bd_net [get_bd_pins $ps/pl_clk0] \
    [get_bd_pins $ps/maxihpm0_fpd_aclk] \
    [get_bd_pins $ps/maxihpm1_fpd_aclk]

validate_bd_design
save_bd_design

set bd_file [get_files */${design_name}.bd]
generate_target all $bd_file
set wrapper [make_wrapper -files $bd_file -top]
add_files -norecurse $wrapper
set_property top ${design_name}_wrapper [current_fileset]
update_compile_order -fileset sources_1

puts "CREATED_BLOCK_DESIGN=$bd_file"
puts "TOP_MODULE=[get_property top [current_fileset]]"
close_project
