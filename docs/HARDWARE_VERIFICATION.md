# Build, verification, and KR260 runbook

## Local results (2026-08-28)

The following were executed in the available environment:

| Stage | Result |
|---|---|
| HDF5 metadata/range inspection | 12 datasets confirmed; no non-finite values |
| NumPy unit/CLI tests | 8 passed |
| Real-HDF5 software path | 20,000-event smoke test passed; final 2,241-event partial-chunk test passed; zero mismatches |
| Stage-B RTL simulation | XSim datapath PASS, 12 events; strict equality boundaries, all pass combinations, multiple/one-event packets, malformed `TKEEP`, stalls, stable output under backpressure, and `TLAST`. A second self-checking AXI-Lite test covers defaults, simultaneous and split write channels, byte strobes, and readback; it was added after the execution host lost access to Vivado and therefore remains to be run with `make sim`. |
| Trigger block design | Vivado 2025.2 `validate_bd_design` passed |
| Loopback block design | Vivado 2025.2 `validate_bd_design` passed |
| Trigger synthesis/implementation | completed, bitstream/bin/XSA generated |
| Trigger timing | 100 MHz constraint met; WNS 5.801 ns, TNS 0, WHS 0.010 ns, THS 0 |
| Trigger utilization | 4,342 total LUTs, 3,656 logic LUTs, 544 LUTRAMs, 142 SRLs, 6,635 FFs, 2 RAMB36, 1 RAMB18, 0 URAM, 0 DSP; custom trigger hierarchy is 101 LUTs/147 FFs |
| Trigger routed DRC | no error or critical-warning class entries; four advisory warnings from AXI DMA/SmartConnect (three BRAM NO_CHANGE collision advisories and one no-routable-load advisory) |
| Loopback synthesis/implementation | completed, bitstream/bin/XSA generated |
| Loopback timing | 100 MHz constraint met; WNS 5.525 ns, TNS 0, WHS 0.011 ns, THS 0 |
| Loopback utilization | 4,387 total LUTs, 3,699 logic LUTs, 544 LUTRAMs, 144 SRLs, 6,840 FFs, 2 RAMB36, 2 RAMB18, 0 URAM, 0 DSP |
| Loopback routed DRC | no error or critical-warning class entries; four AXI DMA BRAM NO_CHANGE collision advisories |

The authoritative generated reports are:

- `reports/trigger_timing_summary.rpt`
- `reports/trigger_utilization.rpt`
- `reports/trigger_drc.rpt`
- `reports/trigger_build_summary.txt`

Equivalent `reports/loopback_*` reports were generated. Both Vivado block
designs use AXI DMA simple/direct-register mode with MM2S and S2MM enabled;
scatter-gather is disabled.

## Physical KR260 results (2026-09-17)

The connected KR260 ran Ubuntu 22.04.5 LTS, kernel
`5.15.0-1076-xilinx-zynqmp`, Python 3.10.12, and PYNQ 3.0.1. The host selected
the carrier's FT4232H `if01` UART at 115200/8-N-1 and performed login, sudo,
deployment, and test control with `software/kr260_uart.py`.

| Stage | Result |
|---|---|
| PYNQ load and identity | FCLK0 99.999 MHz; version `0x00010000`; capabilities `0x0000000f`; contiguous buffer allocation below 4 GiB passed |
| Stage A loopback | 4,097 64-bit events; zero mismatches; measured DMA interval 0.000415 s / 157.974 bidirectional MB/s |
| Stage C deterministic trigger | Actual `[0,0,0,5,6,7,6,5,0]` exactly matched expected; zero mismatches |
| Stage D, one chunk | 20,000 real HDF5 events; zero mismatches and keep errors; measured DMA interval 0.000701 s / 342.546 MB/s / 28.545M events/s |
| Stage D, multiple chunks | 22,241 events in 3 chunks including a 2,241-event tail; zero mismatches and keep errors; measured DMA interval 0.001477 s / 180.641 MB/s / 15.053M events/s |

Machine-readable results are in `reports/board_pynq_20k.json` and
`reports/board_pynq_multichunk.json`; the environment and Stage A/C summary is
in `reports/board_pynq_summary.txt`. Throughput numbers are single-run DMA
interval measurements including buffer synchronization but excluding HDF5
read and conversion, so they are validation observations rather than sustained
performance guarantees.

The board's `/usr/bin/xclbinutil` segfaulted while PYNQ attempted to synthesize
an XCLBIN from HWH metadata. The verified backend therefore uses PYNQ
`Bitstream` loading, explicitly sets FCLK0 to 100 MHz, and uses the design's
fixed MMIO addresses. Standard `Overlay`/HWH mode remains selectable with
`--pynq-loader overlay` for images with a working `xclbinutil`.

## What is not yet verified

The PYNQ path is verified. The alternative generic-UIO/u-dma-buf device-tree
overlay path has not been exercised on this board image. Long-duration stress,
thermal behavior, interrupt-driven operation, and controlled 40 MHz pacing
also remain unverified. The software still reports `hardware_executed: false`
in `--software-only` mode.

## Board image requirements

Use a KR260 Linux image whose base device tree exports `fpga_full` and `amba`,
and install:

- `fpgautil` (plus `xmutil` when provided by the image);
- `uio_pdrv_genirq` with `of_id=generic-uio`;
- the `u-dma-buf` kernel module;
- Python 3, NumPy, and h5py.

The provided overlays create `/dev/uio*` mappings for the DMA and trigger and
two 4 MiB contiguous `/dev/udmabuf*` buffers constrained to 32-bit physical
addresses. The Python backend refuses an address above 4 GiB because this
prototype configures AXI DMA with a 32-bit address width.

Alternatively, use a PYNQ 3.x image and run the application as root in its
PYNQ virtual environment. Preserve `BOARD`, `XILINX_XRT`,
`PYNQ_JUPYTER_NOTEBOOKS`, and `VIRTUAL_ENV` across sudo. The verified PYNQ
backend does not require the two u-dma-buf device-tree buffers.

## Stage A: DMA loopback

Build and deploy the loopback image, in which `M_AXIS_MM2S` connects directly
to `S_AXIS_S2MM` at 64 bits:

```bash
make bitstream MODE=loopback JOBS=4 VIVADO=vivado
make overlays DTC=dtc
sudo ./deploy/install_overlay.sh loopback
python3 software/loopback_test.py --events 4097
```

Required result: `mismatches=0`. The non-power-of-two size ensures the final
beat and DMA-generated `TLAST` are exercised. If it times out, inspect both DMA
status values printed by the exception, confirm the two u-dma-buf physical
addresses are below `0x100000000`, and check the kernel log after overlay load.

## Stage C: deterministic trigger

```bash
make bitstream MODE=trigger JOBS=4 VIVADO=vivado
sudo ./deploy/install_overlay.sh trigger
python3 software/deterministic_trigger_test.py
```

Required result: the `actual` and `expected` lists are identical and
`mismatches=0`. This test writes and reads back thresholds without rebuilding
the PL, then covers below/equal/above and HT-only/AD-only/both/neither values.

## Stage D: HDF5 and multiple chunks

First test a small real chunk, then a multi-chunk range with a partial final
chunk:

```bash
python3 software/kr260_trigger.py Trigger_food_Data.h5 \
  --sample bkg --count 20000 --chunk-size 20000 \
  --ht-cut 218 --ad-cut 250.8929737472539

python3 software/kr260_trigger.py Trigger_food_Data.h5 \
  --sample bkg --start 1640000 --count 22241 --chunk-size 10000 \
  --ht-cut 218 --ad-cut 250.8929737472539 \
  --json-report board-hdf5-report.json
```

Required result: `hardware_executed` is true, `mismatches` and `keep_errors`
are zero, the second run reports three chunks, and all chunks complete without
timeout. `hdf5_read_seconds` excludes conversion and DMA. `dma_seconds` covers
buffer cache synchronization plus hardware transfer; bidirectional MB/s and
trigger events/s use that DMA measurement and do not include SD-card access.

## Error handling and recovery

S2MM is programmed before MM2S to prevent a result-stream deadlock. Every poll
checks both DMA error masks; a timeout resets both channels. Context managers
unmap and close UIO and DMA buffers even after exceptions. Reload the overlay
if a board/kernel error leaves the PL or UIO devices in an uncertain state.

The design uses polling, so no PL-to-PS interrupt is required in this version.
Add interrupts only after this direct-register baseline passes all four stages.
