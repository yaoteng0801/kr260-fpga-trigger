"""Minimal Linux userspace AXI DMA, UIO, and u-dma-buf access.

This backend deliberately does not depend on PYNQ or XRT. It targets a normal
KR260 Linux image with ``uio_pdrv_genirq`` and ``u-dma-buf`` available.
"""

from __future__ import annotations

import mmap
import os
from pathlib import Path
import struct
import time
from typing import Optional

import numpy as np


class HardwareAccessError(RuntimeError):
    pass


def _read_int(path: Path) -> int:
    return int(path.read_text(encoding="ascii").strip(), 0)


def find_uio(name: str) -> Path:
    for entry in sorted(Path("/sys/class/uio").glob("uio*")):
        try:
            if (entry / "name").read_text(encoding="ascii").strip() == name:
                return Path("/dev") / entry.name
        except OSError:
            continue
    raise HardwareAccessError(f"UIO device named {name!r} was not found")


class UioMap:
    def __init__(self, name: str, path: Optional[str] = None):
        self.path = Path(path) if path else find_uio(name)
        sys_entry = Path("/sys/class/uio") / self.path.name
        self.size = _read_int(sys_entry / "maps/map0/size")
        self.fd = os.open(self.path, os.O_RDWR | os.O_SYNC)
        self.mapping = mmap.mmap(
            self.fd,
            self.size,
            flags=mmap.MAP_SHARED,
            prot=mmap.PROT_READ | mmap.PROT_WRITE,
        )

    def read32(self, offset: int) -> int:
        return struct.unpack_from("<I", self.mapping, offset)[0]

    def write32(self, offset: int, value: int) -> None:
        struct.pack_into("<I", self.mapping, offset, value & 0xFFFF_FFFF)

    def close(self) -> None:
        self.mapping.close()
        os.close(self.fd)

    def __enter__(self) -> "UioMap":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class Udmabuf:
    DMA_BIDIRECTIONAL = 0
    DMA_TO_DEVICE = 1
    DMA_FROM_DEVICE = 2

    def __init__(self, device: str):
        self.path = Path(device)
        self.name = self.path.name
        candidates = [
            Path("/sys/class/u-dma-buf") / self.name,
            Path("/sys/class/udmabuf") / self.name,
        ]
        self.sysfs = next((p for p in candidates if p.exists()), None)
        if self.sysfs is None:
            raise HardwareAccessError(f"sysfs entry for {self.path} was not found")
        self.size = _read_int(self.sysfs / "size")
        self.phys_addr = _read_int(self.sysfs / "phys_addr")
        if self.phys_addr > 0xFFFF_FFFF:
            raise HardwareAccessError(
                f"{self.name} physical address 0x{self.phys_addr:x} exceeds the DMA's 32-bit address width"
            )
        self.fd = os.open(self.path, os.O_RDWR)
        self.mapping = mmap.mmap(
            self.fd,
            self.size,
            flags=mmap.MAP_SHARED,
            prot=mmap.PROT_READ | mmap.PROT_WRITE,
        )

    def array(self, dtype: np.dtype, count: int) -> np.ndarray:
        dtype = np.dtype(dtype)
        if count * dtype.itemsize > self.size:
            raise HardwareAccessError(
                f"{count} {dtype} items need {count * dtype.itemsize} bytes, {self.name} has {self.size}"
            )
        return np.ndarray((count,), dtype=dtype, buffer=self.mapping)

    def _sync(self, target: str, size: int, direction: int) -> None:
        if size < 0 or size > self.size:
            raise HardwareAccessError(f"invalid sync size {size} for {self.name}")
        # u-dma-buf rounds cache operations to cache lines. These persistent
        # attributes are more readable and more widely supported than its
        # packed single-write command format.
        (self.sysfs / "sync_offset").write_text("0", encoding="ascii")
        (self.sysfs / "sync_size").write_text(str(size), encoding="ascii")
        (self.sysfs / "sync_direction").write_text(str(direction), encoding="ascii")
        (self.sysfs / target).write_text("1", encoding="ascii")

    def sync_for_device(self, size: int, direction: int) -> None:
        self._sync("sync_for_device", size, direction)

    def sync_for_cpu(self, size: int, direction: int) -> None:
        self._sync("sync_for_cpu", size, direction)

    def close(self) -> None:
        self.mapping.close()
        os.close(self.fd)


class AxiDma:
    MM2S_DMACR = 0x00
    MM2S_DMASR = 0x04
    MM2S_SA = 0x18
    MM2S_SA_MSB = 0x1C
    MM2S_LENGTH = 0x28
    S2MM_DMACR = 0x30
    S2MM_DMASR = 0x34
    S2MM_DA = 0x48
    S2MM_DA_MSB = 0x4C
    S2MM_LENGTH = 0x58

    CR_RUNSTOP = 1 << 0
    CR_RESET = 1 << 2
    SR_IDLE = 1 << 1
    SR_ERROR_MASK = 0x0000_0770
    SR_IRQ_MASK = 0x0000_7000

    def __init__(self, regs: UioMap):
        self.regs = regs
        self.reset()

    def reset(self, timeout_s: float = 1.0) -> None:
        self.regs.write32(self.MM2S_DMACR, self.CR_RESET)
        deadline = time.monotonic() + timeout_s
        while self.regs.read32(self.MM2S_DMACR) & self.CR_RESET:
            if time.monotonic() > deadline:
                raise HardwareAccessError("AXI DMA reset timed out")
        self.regs.write32(self.MM2S_DMASR, self.SR_IRQ_MASK)
        self.regs.write32(self.S2MM_DMASR, self.SR_IRQ_MASK)
        self.regs.write32(self.MM2S_DMACR, self.CR_RUNSTOP)
        self.regs.write32(self.S2MM_DMACR, self.CR_RUNSTOP)

    def _raise_on_error(self, status: int, channel: str) -> None:
        if status & self.SR_ERROR_MASK:
            raise HardwareAccessError(f"AXI DMA {channel} error, DMASR=0x{status:08x}")

    def transfer(
        self,
        src_addr: int,
        src_nbytes: int,
        dst_addr: int,
        dst_nbytes: int,
        timeout_s: float = 5.0,
    ) -> None:
        if not (0 < src_nbytes < (1 << 26)) or not (0 < dst_nbytes < (1 << 26)):
            raise ValueError("simple-DMA transfer lengths must be in [1, 2^26-1]")

        self.regs.write32(self.MM2S_DMASR, self.SR_IRQ_MASK)
        self.regs.write32(self.S2MM_DMASR, self.SR_IRQ_MASK)

        # Arm receive first. The destination LENGTH write starts S2MM.
        self.regs.write32(self.S2MM_DA, dst_addr)
        self.regs.write32(self.S2MM_DA_MSB, dst_addr >> 32)
        self.regs.write32(self.S2MM_LENGTH, dst_nbytes)

        self.regs.write32(self.MM2S_SA, src_addr)
        self.regs.write32(self.MM2S_SA_MSB, src_addr >> 32)
        self.regs.write32(self.MM2S_LENGTH, src_nbytes)

        deadline = time.monotonic() + timeout_s
        while True:
            mm2s = self.regs.read32(self.MM2S_DMASR)
            s2mm = self.regs.read32(self.S2MM_DMASR)
            self._raise_on_error(mm2s, "MM2S")
            self._raise_on_error(s2mm, "S2MM")
            if (mm2s & self.SR_IDLE) and (s2mm & self.SR_IDLE):
                return
            if time.monotonic() > deadline:
                self.reset()
                raise HardwareAccessError(
                    f"AXI DMA timed out; MM2S_DMASR=0x{mm2s:08x}, S2MM_DMASR=0x{s2mm:08x}"
                )


class LinuxDmaSession:
    def __init__(
        self,
        dma_uio_name: str = "kr260-trigger-dma",
        input_device: str = "/dev/udmabuf0",
        output_device: str = "/dev/udmabuf1",
        dma_uio_path: Optional[str] = None,
    ):
        self.dma_regs = UioMap(dma_uio_name, dma_uio_path)
        self.dma = AxiDma(self.dma_regs)
        self.input = Udmabuf(input_device)
        self.output = Udmabuf(output_device)

    def transfer_array(
        self,
        source: np.ndarray,
        output_dtype: np.dtype,
        output_count: int,
        timeout_s: float = 5.0,
    ) -> tuple[np.ndarray, float]:
        source = np.ascontiguousarray(source)
        input_view = self.input.array(source.dtype, source.size)
        output_view = self.output.array(output_dtype, output_count)
        input_view[:] = source.reshape(-1)
        output_view[:] = 0

        start = time.perf_counter()
        self.input.sync_for_device(source.nbytes, Udmabuf.DMA_TO_DEVICE)
        self.output.sync_for_device(output_view.nbytes, Udmabuf.DMA_FROM_DEVICE)
        self.dma.transfer(
            self.input.phys_addr,
            source.nbytes,
            self.output.phys_addr,
            output_view.nbytes,
            timeout_s,
        )
        self.output.sync_for_cpu(output_view.nbytes, Udmabuf.DMA_FROM_DEVICE)
        elapsed = time.perf_counter() - start
        return output_view.copy(), elapsed

    def close(self) -> None:
        try:
            self.dma.reset()
        finally:
            self.output.close()
            self.input.close()
            self.dma_regs.close()

    def __enter__(self) -> "LinuxDmaSession":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class TriggerRegisters:
    HT_CUT = 0x00
    AD_CUT = 0x04
    VERSION = 0x08
    CAPABILITIES = 0x0C

    def __init__(self, uio_name: str = "kr260-axis-trigger", path: Optional[str] = None):
        self.regs = UioMap(uio_name, path)

    def configure(self, ht_cut_q: int, ad_cut_q: int) -> None:
        self.regs.write32(self.HT_CUT, ht_cut_q)
        self.regs.write32(self.AD_CUT, ad_cut_q)
        readback = (self.regs.read32(self.HT_CUT), self.regs.read32(self.AD_CUT))
        if readback != (ht_cut_q, ad_cut_q):
            raise HardwareAccessError(
                f"trigger threshold readback failed: wrote {(ht_cut_q, ad_cut_q)}, read {readback}"
            )

    def close(self) -> None:
        self.regs.close()

    def __enter__(self) -> "TriggerRegisters":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class PynqMmioMap:
    """Adapt PYNQ MMIO to the read32/write32 interface used by AxiDma."""

    def __init__(self, base_address: int, length: int = 0x10000):
        try:
            from pynq import MMIO
        except ImportError as exc:
            raise HardwareAccessError(
                "PYNQ is unavailable; run this backend on a PYNQ-enabled KR260 image"
            ) from exc
        self.mmio = MMIO(base_address, length)

    def read32(self, offset: int) -> int:
        return int(self.mmio.read(offset, 4))

    def write32(self, offset: int, value: int) -> None:
        self.mmio.write(offset, value & 0xFFFF_FFFF)


class PynqDmaSession:
    """PYNQ Overlay/MMIO/buffer backend for the KR260 trigger design."""

    DMA_BASE = 0xA000_0000
    TRIGGER_BASE = 0xA001_0000
    REGISTER_RANGE = 0x0001_0000

    def __init__(
        self,
        bitstream: str | Path,
        buffer_size: int = 4 * 1024 * 1024,
        download: bool = True,
        loader: str = "bitstream",
        clock_mhz: float = 100.0,
        enable_trigger: bool = True,
    ):
        bitstream_path = Path(bitstream).expanduser().resolve()
        hwh_path = bitstream_path.with_suffix(".hwh")
        if not bitstream_path.is_file():
            raise HardwareAccessError(f"PYNQ bitstream was not found: {bitstream_path}")
        if loader not in {"bitstream", "overlay"}:
            raise ValueError("PYNQ loader must be 'bitstream' or 'overlay'")
        if loader == "overlay" and not hwh_path.is_file():
            raise HardwareAccessError(
                f"PYNQ hardware handoff was not found: {hwh_path}; "
                "the .bit and .hwh basenames must match"
            )
        if buffer_size <= 0:
            raise ValueError("PYNQ buffer size must be positive")
        if clock_mhz <= 0:
            raise ValueError("PYNQ clock frequency must be positive")

        try:
            from pynq import Bitstream, Clocks, Overlay, allocate
        except ImportError as exc:
            raise HardwareAccessError(
                "PYNQ is unavailable; run this backend on a PYNQ-enabled KR260 image"
            ) from exc

        if loader == "overlay":
            self.overlay = Overlay(str(bitstream_path), download=download)
        else:
            # This design uses fixed, documented MMIO addresses and does not
            # require automatic IP-driver discovery.  Bitstream mode avoids
            # PYNQ's synthetic-xclbin generation, which is useful on board
            # images where xclbinutil is unavailable or broken.
            Clocks.fclk0_mhz = float(clock_mhz)
            self.overlay = Bitstream(str(bitstream_path))
            if download:
                self.overlay.download()
        self.dma_regs = PynqMmioMap(self.DMA_BASE, self.REGISTER_RANGE)
        self.trigger_regs = (
            PynqMmioMap(self.TRIGGER_BASE, self.REGISTER_RANGE)
            if enable_trigger
            else None
        )
        self.dma = AxiDma(self.dma_regs)
        self.input = None
        self.output = None
        try:
            self.input = allocate(shape=(buffer_size,), dtype=np.uint8)
            self.output = allocate(shape=(buffer_size,), dtype=np.uint8)
            for name, buffer in (("input", self.input), ("output", self.output)):
                address = int(buffer.device_address)
                if address > 0xFFFF_FFFF:
                    raise HardwareAccessError(
                        f"PYNQ {name} buffer address 0x{address:x} exceeds the DMA's "
                        "32-bit address width"
                    )
        except Exception:
            self._free_buffers()
            raise

    def configure_trigger(self, ht_cut_q: int, ad_cut_q: int) -> None:
        if self.trigger_regs is None:
            raise HardwareAccessError("this PYNQ session was opened without trigger MMIO")
        self.trigger_regs.write32(TriggerRegisters.HT_CUT, ht_cut_q)
        self.trigger_regs.write32(TriggerRegisters.AD_CUT, ad_cut_q)
        readback = (
            self.trigger_regs.read32(TriggerRegisters.HT_CUT),
            self.trigger_regs.read32(TriggerRegisters.AD_CUT),
        )
        if readback != (ht_cut_q, ad_cut_q):
            raise HardwareAccessError(
                f"trigger threshold readback failed: wrote {(ht_cut_q, ad_cut_q)}, "
                f"read {readback}"
            )

    def trigger_identity(self) -> tuple[int, int]:
        if self.trigger_regs is None:
            raise HardwareAccessError("this PYNQ session was opened without trigger MMIO")
        return (
            self.trigger_regs.read32(TriggerRegisters.VERSION),
            self.trigger_regs.read32(TriggerRegisters.CAPABILITIES),
        )

    def transfer_array(
        self,
        source: np.ndarray,
        output_dtype: np.dtype,
        output_count: int,
        timeout_s: float = 5.0,
    ) -> tuple[np.ndarray, float]:
        source = np.ascontiguousarray(source)
        output_dtype = np.dtype(output_dtype)
        output_nbytes = output_count * output_dtype.itemsize
        if source.nbytes > self.input.nbytes:
            raise HardwareAccessError(
                f"input needs {source.nbytes} bytes, PYNQ buffer has {self.input.nbytes}"
            )
        if output_nbytes > self.output.nbytes:
            raise HardwareAccessError(
                f"output needs {output_nbytes} bytes, PYNQ buffer has {self.output.nbytes}"
            )

        input_bytes = np.frombuffer(source, dtype=np.uint8, count=source.nbytes)
        self.input[: source.nbytes] = input_bytes
        self.output[:output_nbytes] = 0

        start = time.perf_counter()
        self.input.flush()
        self.output.flush()
        self.dma.transfer(
            int(self.input.device_address),
            source.nbytes,
            int(self.output.device_address),
            output_nbytes,
            timeout_s,
        )
        self.output.invalidate()
        elapsed = time.perf_counter() - start
        result = np.frombuffer(
            self.output, dtype=output_dtype, count=output_count
        ).copy()
        return result, elapsed

    def _free_buffers(self) -> None:
        for name in ("output", "input"):
            buffer = getattr(self, name, None)
            if buffer is not None:
                try:
                    buffer.freebuffer()
                finally:
                    setattr(self, name, None)

    def close(self) -> None:
        try:
            self.dma.reset()
        finally:
            self._free_buffers()

    def __enter__(self) -> "PynqDmaSession":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
