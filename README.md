# KR260 HDF5 AXI-DMA trigger prototype

This directory contains a reproducible KR260 prototype for this path:

```text
HDF5 on SD card -> h5py/NumPy -> contiguous PS DDR -> AXI DMA MM2S
  -> 64-bit AXI4-Stream trigger -> 32-bit result stream -> AXI DMA S2MM
  -> PS DDR -> exact NumPy comparison
```

The PL never parses HDF5. It implements only a deterministic, programmable
fixed-point predicate. Threshold policy, chunking, file I/O, timing, and
validation remain in PS software.

## What is implemented

- Vivado Tcl regeneration for `trigger` and Stage-A `loopback` designs.
- The KR260 board preset, PS DDR, 100 MHz PL clock/reset, PS AXI-Lite master,
  PS HP0 DDR slave port, SmartConnect, and AXI DMA in simple (non-SG) mode.
- A one-cycle, initiation-interval-one RTL trigger with complete
  `TVALID`/`TREADY` backpressure, `TKEEP`, and `TLAST` handling.
- Runtime-writable HT and anomaly-score thresholds at AXI-Lite address
  `0xa0010000`; AXI DMA control is at `0xa0000000`.
- Two board backends: generic Linux UIO plus `u-dma-buf`, and PYNQ 3.x using
  `Bitstream`, `MMIO`, and physically contiguous PYNQ buffers.
- Chunked HDF5 processing (20,000 events by default), final-partial-chunk
  handling, exact golden comparison, mismatch indices, and separate HDF5 and
  DMA timing.
- Device-tree overlays and deterministic Stage A/C tests.

The fixed-point and result formats are normative in
[`docs/EVENT_FORMAT.md`](docs/EVENT_FORMAT.md). Upstream selection is recorded
in [`docs/PROVENANCE.md`](docs/PROVENANCE.md), and measured local verification
plus the board procedure are in
[`docs/HARDWARE_VERIFICATION.md`](docs/HARDWARE_VERIFICATION.md).

The 13-slide English project overview, written for a physics audience, is available as
[`KR260_FPGA_Trigger_Project_Slides.html`](KR260_FPGA_Trigger_Project_Slides.html).
Open it in a browser and use the arrow keys to navigate or `Ctrl+P` to export
the slides to PDF.

The official AMD/Xilinx platform source is tracked as a submodule at the
commit documented in `docs/PROVENANCE.md`. Clone with submodules when that
reference source is needed:

```bash
git clone --recurse-submodules REPOSITORY_URL
```

## Host prerequisites

- Vivado 2025.2 with the KR260 SOM/carrier board files installed.
- Python 3, NumPy, h5py, and pytest (`requirements-dev.txt`).
- A device-tree compiler for `make overlays`.

Set `VIVADO` and `DTC` on the command line if they are not in `PATH`; no source
file contains a machine-specific tool path. Make invokes Vivado through
`env -u PYTHONPATH` by default so an unrelated host Python environment cannot
poison XSim; override `VIVADO_ENV` only if the local installation requires it.

## Rebuild and local verification

From this directory:

```bash
python3 -m pip install -r requirements-dev.txt
make test
make sim VIVADO=vivado

# Stage-A loopback project and bitstream
make bitstream MODE=loopback JOBS=4 VIVADO=vivado

# Trigger project and bitstream
make bitstream MODE=trigger JOBS=4 VIVADO=vivado

make overlays DTC=dtc
```

`make project MODE=trigger` is the shorter command when only a regenerated,
validated block design is wanted. Generated projects and journals live below
`build/`; deployment products live below `deploy/`; reports live below
`reports/`. No hand editing of a `.xpr` or block diagram is required.

The supplied data can be exercised without a board:

```bash
python3 software/kr260_trigger.py Trigger_food_Data.h5 \
  --sample bkg --count 20000 --chunk-size 20000 --software-only
```

## USB-UART console

The carrier J4 debug connector exposes several FTDI interfaces. The Linux
console is the second interface (`if01`, normally `/dev/ttyUSB1`) at 115200
baud, 8 data bits, no parity, one stop bit, and no flow control. A host-side
helper auto-detects the stable `/dev/serial/by-id` link:

```bash
python3 -m pip install -r requirements-host.txt
python3 software/kr260_uart.py list
python3 software/kr260_uart.py probe
python3 software/kr260_uart.py monitor --seconds 10
python3 software/kr260_uart.py console
```

For routine use, the shorter board controller embeds the verified username,
board paths, PYNQ environment, bitstream names, HDF5 path, and test sizes:

```bash
# Interactive step-by-step menu; asks for the password once.
python3 software/kr260_board.py

# Or run one named step.
python3 software/kr260_board.py info
python3 software/kr260_board.py loopback
python3 software/kr260_board.py deterministic
python3 software/kr260_board.py hdf5
python3 software/kr260_board.py multichunk
python3 software/kr260_board.py verify
```

The default username is `ubuntu`; override it with `--username` if the board
account changes. The password is intentionally never stored and is requested
with hidden input. `verify` runs loopback, restores the trigger design, and
then runs both HDF5 cases in one authenticated UART session.

Press `Ctrl-]` to leave the interactive console; `Ctrl-C` is forwarded to the
board. After logging in, determine whether the board image includes PYNQ with:

```bash
python3 -c 'import pynq; print(pynq.__version__)'
hostname -I
```

For VS Code terminals or scripts that do not use a GUI, raw text can be read
and written directly:

```bash
# Continuously display boot and console output; Ctrl-C stops the monitor.
python3 software/kr260_uart.py monitor

# Send one line and read the reply for two seconds (do not pass passwords here).
python3 software/kr260_uart.py send "uname -a"

# Log in with a hidden password prompt, run a command, and propagate its status.
python3 software/kr260_uart.py exec --username USER \
  "uname -a; cat /etc/os-release; hostname -I; python3 -c 'import pynq; print(pynq.__version__)'"

# Run a root-only board command; the same hidden password authenticates sudo.
python3 software/kr260_uart.py exec --username USER --sudo "xmutil listapps"

# Root PYNQ command while retaining only the required board/XRT variables.
python3 software/kr260_uart.py exec --username USER --sudo --preserve-pynq-env \
  "/usr/local/share/pynq-venv/bin/python3 -c 'from pynq import Device; print(Device.active_device)'"
```

`exec` disables terminal echo while framing command output, uses randomized
markers to recover the complete output and remote return code, and restores
echo before disconnecting. `--password-stdin` is available for controlled
automation; passwords should never be supplied as command-line arguments.
Commands passed to `exec` must be non-interactive; use `sudo -n` rather than a
`sudo` invocation that waits for another password prompt, or select `--sudo`
and omit `sudo` from the remote command.

UART is the board's Linux control console, not the trigger data path. The HDF5
application and DMA backend execute on the KR260; use Ethernet/SCP to transfer
large files after obtaining the board IP address from the console.

## Deploy and test on KR260

The board Linux image needs `fpgautil`, `uio_pdrv_genirq`, and the
[`u-dma-buf`](https://github.com/ikwzm/udmabuf) driver. Install NumPy and h5py
from `requirements-board.txt`. Copy `deploy/`, `software/`, that requirements
file, and the HDF5 file to the board, then run:

```bash
# Stage A: exact 64-bit DMA loopback
sudo ./deploy/install_overlay.sh loopback
python3 software/loopback_test.py --events 4097

# Stages C and D: integrated trigger and real HDF5
sudo ./deploy/install_overlay.sh trigger
python3 software/deterministic_trigger_test.py
python3 software/kr260_trigger.py Trigger_food_Data.h5 \
  --sample bkg --count 20000 --chunk-size 20000 \
  --ht-cut 218.0 --ad-cut 250.8929737472539 \
  --json-report trigger-report.json
```

On a PYNQ image, the same application can load the overlay and allocate its
DMA buffers through PYNQ instead of UIO/u-dma-buf. Copy the matching `.bit`
and `.hwh` files together, then run in the board's PYNQ Python environment
with root permission:

```bash
sudo --preserve-env=BOARD,XILINX_XRT,PYNQ_JUPYTER_NOTEBOOKS,VIRTUAL_ENV \
  /usr/local/share/pynq-venv/bin/python3 software/kr260_trigger.py \
  Trigger_food_Data.h5 --sample bkg --count 20000 \
  --backend pynq --bitstream deploy/kr260_trigger.bit

sudo --preserve-env=BOARD,XILINX_XRT,PYNQ_JUPYTER_NOTEBOOKS,VIRTUAL_ENV \
  /usr/local/share/pynq-venv/bin/python3 software/deterministic_trigger_test.py \
  --backend pynq --bitstream deploy/kr260_trigger.bit
```

The PYNQ backend defaults to `Bitstream` loading, explicitly sets FCLK0 to
100 MHz, and uses the project's fixed MMIO addresses. PYNQ supplies bitstream
loading, MMIO, and physically contiguous buffers while the existing code keeps
the AXI DMA register sequence identical between backends. Standard HWH-driven
loading is also available with `--pynq-loader overlay`; it requires a working
board `xclbinutil` as well as the matching `.hwh` file.

The receiver is armed before the sender in every transfer. The two device-tree
buffers are 4 MiB each, so a trigger chunk may contain at most 524,288 64-bit
events; the default is intentionally much smaller. Thresholds may be changed
between invocations without rebuilding the bitstream.

A physical KR260 was verified on 2026-09-17 with Ubuntu 22.04.5 and PYNQ 3.0.1.
The 4097-event loopback, deterministic trigger cases, a 20,000-event HDF5
chunk, and a three-chunk 22,241-event range all completed with zero mismatches.
See `docs/HARDWARE_VERIFICATION.md` and the `reports/board_pynq_*` artifacts for
the measured results and remaining UIO-path limitations.

## Design boundaries

- AXI DMA runs at its natural burst rate. The 100 MHz PL clock and II=1 trigger
  do **not** claim a physical 40 MHz bunch-crossing cadence. Add an explicit
  stream pacer later if controlled playback is required.
- The optional adaptive threshold controller is not part of this first fixed-
  threshold implementation. It belongs in PS software after Stages A-D pass.
- Truth-labeled `tt`/`aa` efficiencies in the exported notebook are offline
  analysis quantities; they are not observable online background-rate inputs.
- The preserved top-level `create_kr260_project.tcl` and
  `create_generic_block_design.tcl` are legacy user source and are not used by
  this build. They were retained because they were not confidently generated.

## Source layout

```text
hw/rtl/              trigger RTL and AXI-Lite registers
hw/tb/               self-checking RTL testbench
hw/tcl/              clean project, bitstream, and simulation scripts
software/            Linux DMA backend, applications, and golden model
tests/               deterministic NumPy/HDF5/CLI tests
device-tree/         source overlays
deploy/              board loader and generated deployment products
docs/                provenance, formats, inventory, cleanup, board procedure
reports/             generated timing, utilization, DRC, and build summaries
build/               ignored Vivado/XSim generated state
```
