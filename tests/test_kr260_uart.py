from pathlib import Path

import pytest

from software.kr260_uart import (
    UartError,
    classify_console,
    discover_ports,
    extract_command_result,
    select_console_port,
)


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (b"kr260 login: ", "login-prompt"),
        (b"Password: ", "password-prompt"),
        (b"ubuntu@kr260:~$ ", "shell-prompt"),
        (b"booting Linux...", "output-received"),
        (b"", "no-response"),
    ],
)
def test_classify_console(data, expected):
    assert classify_console(data) == expected


def test_discover_by_id_marks_if01_as_console(tmp_path: Path):
    names = [
        "usb-Xilinx_KR_Carrier_Card_SERIAL-if00-port0",
        "usb-Xilinx_KR_Carrier_Card_SERIAL-if01-port0",
        "usb-Xilinx_KR_Carrier_Card_SERIAL-if02-port0",
    ]
    for name in names:
        (tmp_path / name).symlink_to("../../ttyUSB0")

    ports = discover_ports(tmp_path)
    assert [port.interface for port in ports] == ["00", "01", "02"]
    assert [port.interface for port in ports if port.is_console_candidate] == ["01"]


def test_explicit_missing_port_is_rejected(tmp_path: Path):
    with pytest.raises(UartError, match="does not exist"):
        select_console_port(str(tmp_path / "missing"))


def test_extract_remote_command_output_and_status():
    data = (
        b"\r\n__KR260_BEGIN_abc__\r\n"
        b"Linux kria 6.1\r\nPYNQ=yes\r\n"
        b"__KR260_END_abc__:7\r\nkria:~$ "
    )
    result = extract_command_result(
        data, "__KR260_BEGIN_abc__", "__KR260_END_abc__"
    )
    assert result.stdout == "Linux kria 6.1\nPYNQ=yes"
    assert result.returncode == 7


def test_extract_remote_command_requires_markers():
    with pytest.raises(UartError, match="start marker"):
        extract_command_result(b"plain output", "BEGIN", "END")
