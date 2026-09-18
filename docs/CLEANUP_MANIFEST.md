# Obsolete-project cleanup manifest

Before deletion, the following exact manifest was printed. These paths were
classified as generated Vivado/Vitis products or crash/log artifacts inside
this project and removed:

```text
.Xil
kr260_self_driving_trigger.cache
kr260_self_driving_trigger.gen
kr260_self_driving_trigger.hw
kr260_self_driving_trigger.ip_user_files
kr260_self_driving_trigger.sim
kr260_self_driving_trigger.srcs
kr260_self_driving_trigger.xpr
create_generic_block_design.log
create_generic_block_design_2343778.backup.log
create_generic_block_design_2344195.backup.log
create_generic_block_design_2344634.backup.log
hs_err_pid204583.log
hs_err_pid2330907.log
vivado.jou
vivado.log
vivado_1633516.backup.jou
vivado_1633516.backup.log
vivado_1633966.backup.jou
vivado_1633966.backup.log
vivado_1634411.backup.jou
vivado_1634411.backup.log
vivado_2330907.backup.jou
vivado_2330907.backup.log
vivado_2345554.backup.jou
vivado_2345554.backup.log
vivado_pid204583.str
vivado_pid2330907.str
kria-vitis-platforms/kr260/platforms/kr260_pmod_gps/.Xil
kria-vitis-platforms/kr260/platforms/kr260_pmod_gps/hs_err_pid2376324.log
kria-vitis-platforms/kr260/platforms/kr260_pmod_gps/project
kria-vitis-platforms/kr260/platforms/kr260_pmod_gps/vivado.jou
kria-vitis-platforms/kr260/platforms/kr260_pmod_gps/vivado.log
kria-vitis-platforms/kr260/platforms/kr260_pmod_gps/vivado_128.backup.jou
kria-vitis-platforms/kr260/platforms/kr260_pmod_gps/vivado_128.backup.log
kria-vitis-platforms/kr260/platforms/kr260_pmod_gps/vivado_pid2376324.str
kria-vitis-platforms/kr260/platforms/linux.bif
kria-vitis-platforms/kr260/platforms/vitis
kria-vitis-platforms/kr260/platforms/xilinx_kr260_pmod_gps_202610_1
```

A later cleanup removed only build-created root Vivado journals/logs, `xvlog.pb`, project Python `__pycache__`/pytest caches, and four Python `__pycache__` directories in the retained `Vitis_Libraries` submodule. All are reproducible transient files; the reference clone is now Git-clean.

The supplied HDF5 and TeX files, nested Git metadata, official source clone,
documentation, and ambiguous legacy Tcl source were preserved. New generated
Vivado state is isolated below `build/` and ignored by `.gitignore`.
