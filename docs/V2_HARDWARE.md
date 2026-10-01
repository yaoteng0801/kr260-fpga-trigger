# V2 22-item FPGA trigger

## Physics problem and design choice

The original V1 demonstrator decides only two quantities, scalar HT and an
anomaly score.  The extended study contains 22 trigger items: inclusive,
central, and forward jet multiplicities; HT and central HT; MET and central
MET; anomaly detection; dijet mass; and VBF.  A 64-bit V1 event cannot carry
all variables needed by that menu.

V2 therefore uses a PS/PL split that is deliberately easy to validate:

```text
Extended HDF5
    |
    v
ARM/PS: reconstruct 22 trigger variables, quantize, pack, update cuts
    |
    | AXI DMA MM2S: 11 consecutive 64-bit beats per event
    v
FPGA/PL: 22 programmable strict comparisons, decision-mask assembly
    |
    | AXI DMA S2MM: one 32-bit result per event
    v
ARM/PS: exact NumPy comparison, rates, reports, optional cut adaptation
```

The split avoids committing the first V2 prototype to one jet-object wire
format while moving all 22 decisions into FPGA logic.  It also makes every PL
input and output exactly reproducible in software.  This is a replay and
algorithm-validation architecture, not a claim of a complete 40 MHz detector
front end.

## Event protocol

Every floating variable is unsigned fixed point with a common scale of 256.
The PS uses NumPy round-to-nearest/even, maps NaN and negative values to zero,
and saturates at `UINT32_MAX`.

One event is exactly 11 little-endian 64-bit AXI4-Stream beats.  Each beat
contains two 32-bit variables: item `2k` in bits `[31:0]` and item `2k+1` in
bits `[63:32]`.

| Bit index | Trigger item | Bit index | Trigger item |
|---:|---|---:|---|
| 0 | 1j | 11 | 3j_forward |
| 1 | 3j | 12 | 4j_forward |
| 2 | 4j | 13 | 5j_forward |
| 3 | 5j | 14 | 6j_forward |
| 4 | 6j | 15 | HT |
| 5 | 1j_central | 16 | HT_central |
| 6 | 3j_central | 17 | MET |
| 7 | 4j_central | 18 | MET_central |
| 8 | 5j_central | 19 | AD |
| 9 | 6j_central | 20 | dijet_mass |
| 10 | 1j_forward | 21 | VBF |

The final beat must carry `TLAST`; every accepted beat must carry `TKEEP=0xff`.
The comparator is strict: an item passes only when `variable > threshold`.

The 32-bit result is:

- bits `[21:0]`: the 22 item decisions in the order above;
- bit 22: OR of all item decisions;
- bit 23: an input `TKEEP` error occurred in this event;
- bit 24: an early `TLAST` framing error occurred;
- bits `[31:25]`: zero, reserved for future use.

The core accepts one input beat per clock when its downstream is ready.  At
100 MHz, one event starts every 11 clocks and the result appears one clock
after the final beat.  The ideal PL-only ceiling is therefore about 9.09
million events/s; host file I/O and DMA setup reduce measured end-to-end rate.

## Programmable register map

The AXI-Lite trigger block remains at `0xa0010000`; AXI DMA remains at
`0xa0000000`.  This preserves the addresses used by V1 while giving V2 a
distinct version identity.

- `0x00` through `0x54`: 22 writable uint32 thresholds, four bytes apart;
- `0x58`: read-only version, `0x00020000`;
- `0x5c`: read-only capabilities, `0x0000003f`.

Software writes all thresholds, reads all of them back, and checks the version
before starting DMA.  This prevents a V2 packet from being sent accidentally
to the V1 two-item bitstream.

## RTL and Zynq system

`axis_trigger_core_v2.sv` receives two variables per beat, performs two
comparisons, and accumulates the item bits across the 11-beat event.  Its
single-result elastic output register preserves AXI `TVALID/TREADY`
backpressure.  `trigger_axi_lite_regs_v2.sv` provides the threshold bank and
identity registers.  `axis_trigger_top_v2.sv` joins those blocks, and
`axis_trigger_bd_wrapper_v2.v` exposes interfaces for Vivado module-reference
inference.

`create_v2_project.tcl` regenerates a KR260 block design containing the Zynq
UltraScale+ PS, 100 MHz PL clock/reset, AXI SmartConnect, simple-mode AXI DMA,
and the V2 trigger.  `build_v2_bitstream.tcl` runs synthesis and implementation
and exports matching BIT, BIN, HWH, XSA, timing, utilization, and DRC products.

The generated 2026-10-01 design met all 100 MHz timing constraints:

| Quantity | Result |
|---|---:|
| Setup WNS / TNS | +4.985 ns / 0.000 ns |
| Hold WHS / THS | +0.010 ns / 0.000 ns |
| Unrouted nets | 0 |
| Total LUT / FF | 4,971 / 7,409 |
| V2 trigger LUT / FF | 681 / 837 |
| BRAM36 / BRAM18 / DSP | 2 / 1 / 0 |

The four reported DRC warnings are advisory messages inside AMD AXI DMA and
SmartConnect IP; there are no DRC errors or critical warnings.

## Build and verification

```bash
# Python format, controller, and HDF5 tests
make -f Makefile.v2 test

# Self-checking XSim tests for the stream core and AXI-Lite register bank
make -f Makefile.v2 sim VIVADO=vivado

# Regenerate the project, implement it, and export deployment products
make -f Makefile.v2 bitstream VIVADO=vivado JOBS=4

# Compile the Linux device-tree overlay
dtc -@ -I dts -O dtb -o deploy/kr260-trigger-v2.dtbo \
  device-tree/kr260-trigger-v2.dts
```

The XSim stream test covers strict comparisons, 22-bit ordering, backpressure,
normal `TLAST`, early `TLAST`, and invalid `TKEEP`.  The register test covers
all default thresholds, writes, byte strobes, and identity registers.  The
Python suite checks the PS/PL packing contract, quantization, golden model,
register helpers, adaptive controller, and chunked Extended HDF5 path.

## Board use

Copy `deploy/`, `software/`, and the Extended HDF5 file to the board.  PYNQ can
load the matching BIT/HWH pair directly:

```bash
sudo --preserve-env=BOARD,XILINX_XRT,PYNQ_JUPYTER_NOTEBOOKS,VIRTUAL_ENV \
  /usr/local/share/pynq-venv/bin/python3 software/deterministic_trigger_test_v2.py \
  --backend pynq --bitstream deploy/kr260_trigger_v2.bit

sudo --preserve-env=BOARD,XILINX_XRT,PYNQ_JUPYTER_NOTEBOOKS,VIRTUAL_ENV \
  /usr/local/share/pynq-venv/bin/python3 software/kr260_trigger_v2.py \
  Trigger_food_Data_Extended.h5 --sample bkg --count 20000 \
  --backend pynq --bitstream deploy/kr260_trigger_v2.bit \
  --json-report reports/board_v2_20k.json
```

For generic Linux, load `deploy/kr260_trigger_v2.bin` together with
`deploy/kr260-trigger-v2.dtbo` using `deploy/install_overlay_v2.sh`, then run
the same programs with `--backend uio`.

`--adaptive-mode local` or `gradient` updates the 22 thresholds in ARM software
between chunks and writes the next set to the FPGA.  The event comparison
itself remains in PL.  This keeps the slow policy loop separate from the fast,
deterministic data path.

## Compatibility and current validation boundary

All V1 files, bitstreams, CLI commands, HDF5 schema, and UART menu entries are
retained.  V2 uses new filenames and versioned UIO names, so installing or
running it is explicit.

The V2 bitstream has passed RTL simulation, complete Vivado synthesis,
placement, routing, timing sign-off, bitstream generation, and physical KR260
testing on 2026-10-01.  The board ran Ubuntu 22.04.5, PYNQ 3.0.1, and a
99.999 MHz FCLK0.

| Physical board test | Events | Chunks | Result |
|---|---:|---:|---|
| Directed boundaries and all 22 item bits | 69 | 1 | 0 mismatches |
| Fixed cuts, real Extended HDF5 background | 20,000 | 1 | 0 mismatches, 0 stream errors |
| Local adaptive cuts, real Extended HDF5 background | 30,000 | 3 | 0 mismatches, 0 stream errors |

For the 20,000-event case, the measured DMA-only time was 2.702 ms for
1.84 MB of bidirectional traffic: 681 MB/s and 7.40 million events/s.  These
numbers exclude HDF5 read and ARM feature construction.  In the adaptive test,
ARM changed `HT_central` from 230 to 250 after the first chunk and increased
`dijet_mass` from 1000 to 1100 across later chunks; each new 22-cut bank was
written and read back before the next FPGA transfer.

The machine-readable reports are
`reports/board_v2_20k.json` and
`reports/board_v2_adaptive_30k.json`.  The 2.1 GB Extended HDF5 input remains
on the board rather than being committed to this repository.
