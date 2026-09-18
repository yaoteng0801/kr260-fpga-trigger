# KR260 platform provenance

## Installed environment

- Vivado: 2025.2, build 6299465.
- Vitis is not required by this Linux userspace/Vivado-only build. Its executable version was not captured before the execution host changed and is therefore unverified; no Vitis-generated artifact is part of the reproducible flow.
- Device: `xck26-sfvc784-2LV-c`.
- Selected installed board part at build time:
  `xilinx.com:kr260_som_som240_1_connector_kr260_carrier_som240_1_connector_som240_2_connector_kr260_carrier_som240_2_connector:part0:1.1`.
- KR260 SOM board files 1.0 and 1.1 and carrier board files 1.0 and 1.1
  are installed in the Vivado 2025.2 BoardStore.

## Official source selection

- Repository: <https://github.com/Xilinx/kria-vitis-platforms>
- Official release tag selected: `v1.0.1`
- Commit: `fda21f899ed88e8e6cf9ac4c429dabe91777936f`
- The release README declares Vivado/Vitis 2024.1.
- Public KR260 platforms in that release are `kr260_pmod_gps` and
  `kr260_tsn_rs485pmod`.
- Foundation selected: `kr260_pmod_gps`.

No official 2025.2 branch or tag exists in the repository. The local `main`
checkout is commit `60c3f54f72aa9fec83abfef6738465ae72dbe26d` / tag `v1.2`, whose README
targets the newer 2026.1 tools. Using that newer source with an older tool risks
unavailable IP revisions. The older official `v1.0.1` foundation was therefore
selected and then explicitly validated, synthesized, implemented, and timed in
the installed 2025.2 release.

`kr260_pmod_gps` is the smaller of the two public designs. It establishes the
K26/KR260 board part, carrier board connections, and Zynq UltraScale+ PS board
preset without the TSN, RS485, CAN, test-controller, or additional application
logic in `kr260_tsn_rs485pmod`. This project reuses that verified foundation
pattern, then creates only the PS/PL infrastructure needed here. It does not
retain the GPS UART or any other application-specific PL logic.

The source snapshot remains available in the existing
`kria-vitis-platforms/` Git clone. The selected files can be inspected without
changing its current branch, for example:

```bash
git -C kria-vitis-platforms show \
  v1.0.1:kr260/platforms/kr260_pmod_gps/scripts/main.tcl
git -C kria-vitis-platforms show \
  v1.0.1:kr260/platforms/kr260_pmod_gps/scripts/config_bd.tcl
```

## Adaptation into this design

The reproducible Tcl design retains:

- the official KR260 SOM/carrier selection and PS board preset;
- a 100 MHz PS-generated PL clock and synchronized reset;
- PS `M_AXI_HPM0_FPD` for AXI-Lite control;
- PS `S_AXI_HP0_FPD` for PL masters to access the low 2 GiB DDR segment.

It adds AXI DMA in simple mode, separate control/memory SmartConnect instances,
and either a direct 64-bit stream loopback or the custom trigger. DMA interrupt
ports are not needed by the initial polling userspace application and are left
disabled/unconnected. The generated `.xpr` is disposable; `hw/tcl/` is the
source of truth.
