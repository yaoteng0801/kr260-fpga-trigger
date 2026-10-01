"""Register helpers for the 22-threshold V2 trigger hardware."""

from __future__ import annotations

from typing import Protocol, Sequence

from software.hw_access import HardwareAccessError, UioMap
from software.trigger_v2_format import ITEM_NAMES, N_ITEMS


class RegisterMap(Protocol):
    def read32(self, offset: int) -> int: ...

    def write32(self, offset: int, value: int) -> None: ...


class TriggerV2RegisterLayout:
    CUT_BASE = 0x00
    CUT_STRIDE = 0x04
    VERSION = 0x58
    CAPABILITIES = 0x5C
    EXPECTED_VERSION = 0x0002_0000
    EXPECTED_CAPABILITIES = 0x0000_003F

    @classmethod
    def cut_offset(cls, index: int) -> int:
        if not 0 <= index < N_ITEMS:
            raise IndexError(f"V2 cut index must be in [0, {N_ITEMS})")
        return cls.CUT_BASE + cls.CUT_STRIDE * index


def configure_v2_register_map(regs: RegisterMap, cuts_q: Sequence[int]) -> None:
    if len(cuts_q) != N_ITEMS:
        raise ValueError(f"V2 requires exactly {N_ITEMS} thresholds")
    expected = tuple(int(value) & 0xFFFF_FFFF for value in cuts_q)
    for index, value in enumerate(expected):
        regs.write32(TriggerV2RegisterLayout.cut_offset(index), value)
    readback = tuple(
        regs.read32(TriggerV2RegisterLayout.cut_offset(index)) for index in range(N_ITEMS)
    )
    if readback != expected:
        differences = [
            f"{ITEM_NAMES[index]}: wrote {expected[index]}, read {readback[index]}"
            for index in range(N_ITEMS)
            if readback[index] != expected[index]
        ]
        raise HardwareAccessError("V2 threshold readback failed: " + "; ".join(differences))


def v2_identity(regs: RegisterMap) -> tuple[int, int]:
    return (
        regs.read32(TriggerV2RegisterLayout.VERSION),
        regs.read32(TriggerV2RegisterLayout.CAPABILITIES),
    )


class TriggerV2Registers:
    def __init__(
        self,
        uio_name: str = "kr260-axis-trigger-v2",
        path: str | None = None,
    ) -> None:
        self.regs = UioMap(uio_name, path)

    def configure(self, cuts_q: Sequence[int]) -> None:
        configure_v2_register_map(self.regs, cuts_q)

    def identity(self) -> tuple[int, int]:
        return v2_identity(self.regs)

    def close(self) -> None:
        self.regs.close()

    def __enter__(self) -> "TriggerV2Registers":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
