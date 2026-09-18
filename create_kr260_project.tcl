set project_dir [file normalize [file dirname [info script]]]
set project_name kr260_self_driving_trigger
set board_part xilinx.com:kr260_som:part0:1.1

create_project $project_name $project_dir -part xck26-sfvc784-2LV-c -force
set_property board_part $board_part [current_project]
set_property target_language Verilog [current_project]
set_property simulator_language Mixed [current_project]
save_project
puts "CREATED_PROJECT=[get_property DIRECTORY [current_project]]/[current_project].xpr"
puts "BOARD_PART=[get_property board_part [current_project]]"
close_project
