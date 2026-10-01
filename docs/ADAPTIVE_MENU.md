# Extended adaptive trigger menu

The extended menu is a backward-compatible PS/offline and V2 FPGA feature
derived from `Trigger_io_menu20_clean.ipynb`. Despite that notebook name, the
menu contains 22 items: 15 jet-multiplicity items, two HT items, two MET items,
anomaly detection, dijet mass, and VBF.

It does **not** replace `deploy/kr260_trigger.bit`: V1 still consumes one
64-bit `HT + score02` event and evaluates two cuts. The parallel V2 design uses
`deploy/kr260_trigger_v2.bit`, moves all 22 comparisons into PL, and uses the
same reference model for exact result checking. Every V1 board command remains
available.

## Architecture

```text
Extended HDF5 -> chunked PS reader -> 22 trigger variables -> fixed-point packer
                                             |                    |
                                             |                    v
                                             |       AXI DMA -> PL comparators
                                             |                    |
                                             +--> rates/costs <---+
                                                      |
                                             local/gradient update
                                                      |
                                             cuts for next chunk
```

The controller is causal at chunk boundaries: current cuts evaluate the
current chunk, then a proposed update is applied to the next chunk. Event
comparisons are strict `>` in both NumPy and RTL.

## Extended HDF5 contract

For each sample prefix such as `bkg`, `tt`, or `aa`, the following datasets are
required:

| Suffix | Shape | Meaning |
|---|---|---|
| `jet_pt`, `cjet_pt`, `fjet_pt` | `(events, >=6)` | pT-sorted inclusive, central, and forward jets |
| `ht`, `ht_central` | `(events,)` | scalar HT quantities |
| `met`, `met_central` | `(events,)` | scalar MET quantities |
| `score02` | `(events,)` | anomaly score |
| `pair_mjj` | `(events, pairs)` | dijet masses |
| `pair_min_pt` | `(events, pairs)` | smaller jet pT in each pair |
| `pair_deta` | `(events, pairs)` | pair delta-eta quantity |

`njet` is additionally required only when the event-complexity cost has a
nonzero weight. `Npv` is optional monitoring information. The old
`Trigger_food_Data.h5` remains supported by V1 but lacks the fields required by
the 22-item program.

## Running the software menu

Rate-only operation uses no truth-labelled signal data and is the closest
model of an online controller:

```bash
python3 software/adaptive_trigger_menu.py Trigger_food_Data_Extended.h5 \
  --mode local --count 100000 --summary-json adaptive-summary.json
```

An offline MC study may add signal efficiency to the objective:

```bash
python3 software/adaptive_trigger_menu.py Trigger_food_Data_Extended.h5 \
  --mode gradient --signal-samples tt aa --count 100000 \
  --history-json adaptive-history.json
```

The default calibration uses the notebook's 99.981 and 99.977 percentiles. A
positive minimum step prevents discrete observables such as 5j from becoming
permanently frozen. Use `--absolute-vbf-deta` only when stored `pair_deta` is
signed rather than already absolute.

The JSON summary includes `legacy_fpga_cuts.ht_cut` and
`legacy_fpga_cuts.ad_cut`; these remain usable by the unchanged V1 application.

## Controller objective

The objective is an explicit weighted sum of:

- deviation from the requested output rate;
- offline signal inefficiency, when truth-labelled samples are supplied;
- trigger-item cost among accepted events;
- accepted-event jet multiplicity.

Signal cost defaults to zero when no signal sample is supplied, because `tt`
and `aa` truth labels are not live collision-stream inputs. Trigger and event
costs also default to zero rather than being silently calculated and ignored.

## V2 hardware boundary

V2 sends the 22 precomputed trigger variables from PS. They are quantized at
1/256 units and packed two per 64-bit beat, giving exactly 11 AXI4-Stream beats
per event. PL compares those values against 22 AXI-Lite threshold registers and
returns a 32-bit word containing 22 item bits, a total OR bit, and stream-error
flags.

```bash
python3 software/kr260_trigger_v2.py Trigger_food_Data_Extended.h5 \
  --sample bkg --count 20000 --backend pynq \
  --bitstream deploy/kr260_trigger_v2.bit
```

Add `--adaptive-mode local` or `--adaptive-mode gradient` to update thresholds
between chunks. See `docs/V2_HARDWARE.md` for the exact protocol, register map,
RTL, timing results, and board verification procedure.
