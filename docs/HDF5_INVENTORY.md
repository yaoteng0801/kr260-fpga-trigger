# Supplied input inventory

Inspection was performed with h5py metadata access and bounded hyperslabs;
extrema were computed with a chunked scan rather than loading a complete
dataset into memory.

## Preserved files

| File | Size | SHA-256 |
|---|---:|---|
| `Trigger_food_Data.h5` | 79,793,712 bytes | `bb38f0a0cdf2328b53201a3f8efe53d1f2e0f5252dfb51613c68c079545a866c` |
| `Trigger_io.tex` | 127,553 bytes | `f86854f93dccdd6f79294ab8e2f8d7fe5d52b16737cb860a80f3de82e6af2494` |

## HDF5 datasets

All 12 datasets have shape `(1662241,)`, dtype `float32`, contiguous storage,
no HDF5 chunk layout, and no compression. Every value scanned was finite.

| Dataset | Minimum | Maximum |
|---|---:|---:|
| `aa_Npv` | 1 | 55 |
| `aa_ht` | 0 | 4228.5 |
| `aa_njet` | 0 | 8 |
| `aa_score02` | 0.6648159027 | 126652.7421875 |
| `bkg_Npv` | 1 | 60 |
| `bkg_ht` | 0 | 1498.5 |
| `bkg_njet` | 0 | 8 |
| `bkg_score02` | 0.6648159027 | 5903.96142578 |
| `tt_Npv` | 1 | 63 |
| `tt_ht` | 0 | 4197 |
| `tt_njet` | 0 | 8 |
| `tt_score02` | 0.6648159027 | 126716 |

The first hardware version consumes only `<sample>_ht` and
`<sample>_score02`, where sample is `bkg`, `tt`, or `aa`. Dataset names can be
overridden on the command line.

## Exported notebook behavior

`Trigger_io.tex` contains the expected `bkg_*`, `tt_*`, and `aa_*` accesses.
Its primitive comparison is strict `values > cut`, and its total decision is
HT pass OR anomaly-score pass. Its initial percentile-derived cuts are HT 218
and AD approximately 250.8929737472539. It also contains an adaptive 3-by-3
threshold study; that policy is intentionally not placed in the first PL
datapath.
