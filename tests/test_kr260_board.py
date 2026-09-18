from software.kr260_board import (
    BOARD_APP,
    HDF5_FILE,
    deterministic_command,
    hdf5_command,
    loopback_command,
)


def test_default_commands_embed_board_profile():
    loopback = loopback_command()
    deterministic = deterministic_command()
    hdf5 = hdf5_command()

    for command in (loopback, deterministic, hdf5):
        assert f"cd {BOARD_APP}" in command
        assert "--backend pynq" in command
    assert "--events 4097" in loopback
    assert "kr260_loopback.bit" in loopback
    assert "kr260_trigger.bit" in deterministic
    assert str(HDF5_FILE) in hdf5
    assert "--count 20000" in hdf5
    assert "--chunk-size 20000" in hdf5


def test_hdf5_command_accepts_short_overrides():
    command = hdf5_command(
        sample="tt",
        start=10,
        count=25,
        chunk_size=20,
        report="reports/test.json",
    )
    assert "--sample tt" in command
    assert "--start 10" in command
    assert "--count 25" in command
    assert "--chunk-size 20" in command
    assert "--json-report reports/test.json" in command
