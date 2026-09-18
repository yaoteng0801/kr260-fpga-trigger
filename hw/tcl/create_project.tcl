# Recreate the complete KR260 AXI DMA prototype from source.
# Usage: vivado -mode batch -source hw/tcl/create_project.tcl -tclargs trigger

set mode [expr {$argc > 0 ? [lindex $argv 0] : "trigger"}]
if {$mode ni {trigger loopback}} {
    error "mode must be trigger or loopback"
}

set script_dir [file normalize [file dirname [info script]]]
set root_dir [file normalize [file join $script_dir ../..]]
set build_dir [file normalize [file join $root_dir build vivado $mode]]
set project_name "kr260_${mode}"
set bd_name system

# Generated state lives only below build/vivado.
file delete -force $build_dir
file mkdir $build_dir

set board_part [get_board_parts -quiet "*:kr260_som:*" -latest_file_version]
if {[llength $board_part] == 0} {
    error "KR260 SOM board files are unavailable. Install the AMD board store files first."
}
set board_part [lindex $board_part 0]
set part_name [get_property PART_NAME $board_part]
puts "SELECTED_BOARD_PART=$board_part"
puts "SELECTED_DEVICE=$part_name"

create_project $project_name $build_dir -part $part_name -force
set_property BOARD_PART $board_part [current_project]
set_property TARGET_LANGUAGE Verilog [current_project]
set_property SIMULATOR_LANGUAGE Mixed [current_project]
catch {
    set_property board_connections {
        som240_1_connector xilinx.com:kr260_carrier:som240_1_connector:1.0
        som240_2_connector xilinx.com:kr260_carrier:som240_2_connector:1.0
    } [current_project]
}

if {$mode eq "trigger"} {
    add_files -norecurse [list \
        [file join $root_dir hw rtl axis_trigger_core.sv] \
        [file join $root_dir hw rtl trigger_axi_lite_regs.sv] \
        [file join $root_dir hw rtl axis_trigger_top.sv] \
        [file join $root_dir hw rtl axis_trigger_bd_wrapper.v]]
    update_compile_order -fileset sources_1
}

create_bd_design $bd_name
current_bd_design $bd_name

# The PS preset and board connection are taken from the official
# kr260_pmod_gps platform foundation. Only PS, DDR, clock/reset and the two
# required PS/PL AXI ports are retained here.
set ps [create_bd_cell -type ip -vlnv xilinx.com:ip:zynq_ultra_ps_e:* ps]
apply_bd_automation -rule xilinx.com:bd_rule:zynq_ultra_ps_e \
    -config {apply_board_preset "1"} $ps
set_property -dict [list \
    CONFIG.PSU__USE__M_AXI_GP0 {1} \
    CONFIG.PSU__USE__M_AXI_GP1 {0} \
    CONFIG.PSU__USE__S_AXI_GP2 {1} \
    CONFIG.PSU__CRL_APB__PL0_REF_CTRL__FREQMHZ {100}] $ps

set reset [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:* reset_100m]

set control_smc [create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:* control_smc]
set control_mi [expr {$mode eq "trigger" ? 2 : 1}]
set_property -dict [list CONFIG.NUM_SI {1} CONFIG.NUM_MI $control_mi] $control_smc

set memory_smc [create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:* memory_smc]
set_property -dict [list CONFIG.NUM_SI {2} CONFIG.NUM_MI {1}] $memory_smc

set dma [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_dma:* dma]
set s2mm_stream_width [expr {$mode eq "trigger" ? 32 : 64}]
set_property -dict [list \
    CONFIG.c_include_sg {0} \
    CONFIG.c_include_mm2s {1} \
    CONFIG.c_include_s2mm {1} \
    CONFIG.c_addr_width {32} \
    CONFIG.c_sg_length_width {26} \
    CONFIG.c_m_axi_mm2s_data_width {64} \
    CONFIG.c_m_axis_mm2s_tdata_width {64} \
    CONFIG.c_m_axi_s2mm_data_width $s2mm_stream_width \
    CONFIG.c_s_axis_s2mm_tdata_width $s2mm_stream_width \
    CONFIG.c_include_mm2s_dre {0} \
    CONFIG.c_include_s2mm_dre {0} \
    CONFIG.c_mm2s_burst_size {16} \
    CONFIG.c_s2mm_burst_size {16}] $dma

if {$mode eq "trigger"} {
    set trigger [create_bd_cell -type module -reference axis_trigger_bd_wrapper trigger]
}

# PS AXI-Lite master -> DMA control and trigger threshold registers.
connect_bd_intf_net [get_bd_intf_pins ps/M_AXI_HPM0_FPD] [get_bd_intf_pins control_smc/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins control_smc/M00_AXI] [get_bd_intf_pins dma/S_AXI_LITE]
if {$mode eq "trigger"} {
    connect_bd_intf_net [get_bd_intf_pins control_smc/M01_AXI] [get_bd_intf_pins trigger/S_AXI]
}

# Both DMA memory masters share the PS S_AXI_HP0_FPD DDR port.
connect_bd_intf_net [get_bd_intf_pins dma/M_AXI_MM2S] [get_bd_intf_pins memory_smc/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins dma/M_AXI_S2MM] [get_bd_intf_pins memory_smc/S01_AXI]
connect_bd_intf_net [get_bd_intf_pins memory_smc/M00_AXI] [get_bd_intf_pins ps/S_AXI_HP0_FPD]

if {$mode eq "trigger"} {
    connect_bd_intf_net [get_bd_intf_pins dma/M_AXIS_MM2S] [get_bd_intf_pins trigger/S_AXIS]
    connect_bd_intf_net [get_bd_intf_pins trigger/M_AXIS] [get_bd_intf_pins dma/S_AXIS_S2MM]
} else {
    connect_bd_intf_net [get_bd_intf_pins dma/M_AXIS_MM2S] [get_bd_intf_pins dma/S_AXIS_S2MM]
}

set pl_clk [get_bd_pins ps/pl_clk0]
set resetn [get_bd_pins ${reset}/peripheral_aresetn]
connect_bd_net $pl_clk \
    [get_bd_pins ps/maxihpm0_fpd_aclk] \
    [get_bd_pins ps/saxihp0_fpd_aclk] \
    [get_bd_pins ${reset}/slowest_sync_clk] \
    [get_bd_pins control_smc/aclk] \
    [get_bd_pins memory_smc/aclk] \
    [get_bd_pins dma/s_axi_lite_aclk] \
    [get_bd_pins dma/m_axi_mm2s_aclk] \
    [get_bd_pins dma/m_axi_s2mm_aclk]
connect_bd_net [get_bd_pins ps/pl_resetn0] [get_bd_pins ${reset}/ext_reset_in]
connect_bd_net $resetn \
    [get_bd_pins control_smc/aresetn] \
    [get_bd_pins memory_smc/aresetn] \
    [get_bd_pins dma/axi_resetn]
if {$mode eq "trigger"} {
    connect_bd_net $pl_clk [get_bd_pins trigger/aclk]
    connect_bd_net $resetn [get_bd_pins trigger/aresetn]
}

# Stable userspace-visible control addresses; automatically map DMA masters to
# every reachable PS DDR segment after these two fixed assignments.
set ps_data [get_bd_addr_spaces ps/Data]
set dma_regs [get_bd_addr_segs dma/S_AXI_LITE/Reg]
assign_bd_address -offset 0xA0000000 -range 0x00010000 \
    -target_address_space $ps_data $dma_regs -force
if {$mode eq "trigger"} {
    set trigger_regs [get_bd_addr_segs -of_objects [get_bd_intf_pins trigger/S_AXI]]
    if {[llength $trigger_regs] != 1} {
        error "expected one trigger AXI-Lite address segment, got: $trigger_regs"
    }
    assign_bd_address -offset 0xA0010000 -range 0x00010000 \
        -target_address_space $ps_data $trigger_regs -force
}
set ddr_low [get_bd_addr_segs ps/SAXIGP2/HP0_DDR_LOW]
assign_bd_address -target_address_space [get_bd_addr_spaces dma/Data_MM2S] $ddr_low
assign_bd_address -target_address_space [get_bd_addr_spaces dma/Data_S2MM] $ddr_low

validate_bd_design
save_bd_design
set bd_file [get_files */${bd_name}.bd]
generate_target all $bd_file
set wrapper [make_wrapper -files $bd_file -top]
add_files -norecurse $wrapper
set_property top ${bd_name}_wrapper [current_fileset]
update_compile_order -fileset sources_1
set_property synth_checkpoint_mode None $bd_file

puts "PROJECT_FILE=[get_property DIRECTORY [current_project]]/${project_name}.xpr"
puts "MODE=$mode"
close_project
