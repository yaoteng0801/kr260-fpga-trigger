# Event, threshold, and result format

This document is the PS/PL interface contract. The implementation shared by
packing and the software golden model is `software/trigger_format.py`.

## Source and quantization

Both observed source datasets are one-dimensional HDF5 `float32` arrays.
Conversion is performed by the PS using a `float64` intermediate:

```text
q = saturate_uint32(round_to_nearest_ties_to_even(float64(value) * scale))
```

NumPy `rint` defines round-to-nearest, ties-to-even. Values below zero and
negative infinity saturate to 0; values above the unsigned 32-bit range and
positive infinity saturate to `0xffffffff`; NaN maps to 0. All fields and
comparisons are unsigned.

| Quantity | Source dtype | Scale | Resolution | Observed maximum | Maximum quantized value |
|---|---:|---:|---:|---:|---:|
| HT | `float32` | 2 | 0.5 | 4228.5 | 8457 |
| anomaly `score02` | `float32` | 256 | 1/256 | 126716 | 32,439,296 |

The observed ranges fit comfortably in 32 bits and retain the source's useful
precision without floating-point PL logic.

Thresholds use exactly the same conversion. The notebook-derived defaults are
HT `218.0 -> 436` and AD `250.8929737472539 -> 64229`. The PL predicate is
strict unsigned `>` on quantized values; equality does not pass.

## 64-bit input event word

| Bits | Field |
|---|---|
| `[31:0]` | quantized unsigned HT |
| `[63:32]` | quantized unsigned anomaly score |

The PS buffer is a little-endian `uint64` array, which matches the KR260's
little-endian AArch64 memory layout. The bit positions above are the normative
AXI `TDATA` definition; the lowest-address byte contains HT bits `[7:0]`.
Every event has input `TKEEP=0xff`. AXI DMA asserts input `TLAST` at the end of
each MM2S transfer/chunk.

## 32-bit output result word

| Bit | Meaning |
|---|---|
| 0 | `ht_pass = ht_q > ht_cut_q` |
| 1 | `ad_pass = ad_q > ad_cut_q` |
| 2 | `total_pass = ht_pass OR ad_pass` |
| 3 | debug error: input `TKEEP` was not `0xff` |
| `[31:4]` | zero |

Output `TKEEP` is always `0xf`. One result is emitted for every accepted input
event, and the corresponding input `TLAST` is held and propagated to that
result. This makes an S2MM transaction terminate on exactly one result packet,
including a one-event packet and a final partial chunk.

## AXI-Lite register map

Base address: `0xa0010000`.

| Offset | Access | Meaning |
|---:|---|---|
| `0x00` | R/W | quantized unsigned HT threshold |
| `0x04` | R/W | quantized unsigned AD threshold |
| `0x08` | R | RTL version (`0x00010000`) |
| `0x0c` | R | capabilities (`0x0000000f`) |

Byte write strobes are supported. The Python application writes both cuts and
verifies readback before starting DMA.

## Pipeline behavior

The result is registered, so accepted input to available output latency is one
PL clock. The elastic register accepts and returns one event each clock when
neither interface stalls (initiation interval 1). During backpressure it holds
`TDATA`, `TKEEP`, `TLAST`, and `TVALID` until the downstream handshake.
