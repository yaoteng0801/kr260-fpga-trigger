from argparse import Namespace
from pathlib import Path

from software.kr260_trigger import run


def test_software_only_real_chunk():
    root = Path(__file__).resolve().parents[1]
    args = Namespace(
        hdf5=root / "Trigger_food_Data.h5",
        sample="bkg",
        ht_dataset=None,
        ad_dataset=None,
        start=19_990,
        count=25,
        chunk_size=20,
        ht_cut=218.0,
        ad_cut=250.8929737472539,
        software_only=True,
        backend="uio",
        bitstream=None,
        pynq_buffer_size=4 * 1024 * 1024,
        pynq_loader="bitstream",
        pynq_clock_mhz=100.0,
        dma_uio_name="unused",
        trigger_uio_name="unused",
        input_buffer="unused",
        output_buffer="unused",
        timeout=1.0,
        max_mismatch_indices=20,
        json_report=None,
    )
    report = run(args)
    assert report["events"] == 25
    assert report["chunks"] == 2
    assert report["mismatches"] == 0
    assert report["hardware_executed"] is False
