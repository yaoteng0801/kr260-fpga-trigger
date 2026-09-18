#!/usr/bin/env python3
"""Discover and open the KR260 USB-UART Linux console.

The KR260 J4 debug connector exposes several FTDI interfaces.  AMD documents
the second numbered interface as the Linux UART.  On Linux that is normally
the ``if01`` by-id link (often ``/dev/ttyUSB1``), configured as 115200 8N1
without flow control.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import getpass
import os
from pathlib import Path
import re
import secrets
import select
import shlex
import sys
import termios
import time
import tty

import serial
from serial.tools import list_ports


DEFAULT_BAUD = 115_200
DEFAULT_INTERFACE = "01"
BY_ID_DIR = Path("/dev/serial/by-id")
KRIA_BY_ID_RE = re.compile(
    r"usb-Xilinx_KR_Carrier_Card_(?P<serial>.+)-if(?P<interface>\d+)-port0$"
)


class UartError(RuntimeError):
    """A user-facing UART discovery or access error."""


@dataclass(frozen=True)
class UartPort:
    path: str
    interface: str | None
    serial_number: str | None
    description: str

    @property
    def is_console_candidate(self) -> bool:
        return self.interface == DEFAULT_INTERFACE


@dataclass(frozen=True)
class CommandResult:
    stdout: str
    returncode: int


def discover_ports(by_id_dir: Path = BY_ID_DIR) -> list[UartPort]:
    """Return attached Xilinx KR carrier FTDI ports in stable order."""

    discovered: dict[str, UartPort] = {}
    if by_id_dir.is_dir():
        for path in sorted(by_id_dir.glob("usb-Xilinx_KR_Carrier_Card_*-if*-port0")):
            match = KRIA_BY_ID_RE.fullmatch(path.name)
            if match:
                discovered[str(path)] = UartPort(
                    path=str(path),
                    interface=match.group("interface"),
                    serial_number=match.group("serial"),
                    description="Xilinx KR Carrier Card",
                )

    # Fall back to pyserial enumeration on systems without /dev/serial/by-id.
    if not discovered:
        candidates = []
        for port in list_ports.comports(include_links=True):
            identity = " ".join(
                str(value or "")
                for value in (port.description, port.manufacturer, port.product, port.hwid)
            ).lower()
            if "xilinx" in identity or "kr carrier" in identity:
                candidates.append(port)
        for index, port in enumerate(sorted(candidates, key=lambda item: item.device)):
            interface = f"{index:02d}"
            discovered[port.device] = UartPort(
                path=port.device,
                interface=interface,
                serial_number=port.serial_number,
                description=port.description or "Xilinx serial interface",
            )

    return list(discovered.values())


def select_console_port(explicit_port: str | None = None) -> str:
    if explicit_port:
        path = Path(explicit_port)
        if not path.exists():
            raise UartError(f"serial device does not exist: {explicit_port}")
        return explicit_port

    candidates = [port for port in discover_ports() if port.is_console_candidate]
    if len(candidates) == 1:
        return candidates[0].path
    if not candidates:
        raise UartError(
            "no KR260 if01 UART was found; connect carrier J4 or pass --port explicitly"
        )
    paths = ", ".join(port.path for port in candidates)
    raise UartError(f"multiple KR260 UARTs found ({paths}); choose one with --port")


def open_serial(port: str, baud: int, timeout: float) -> serial.Serial:
    try:
        return serial.Serial(
            port=port,
            baudrate=baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=timeout,
            write_timeout=1.0,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
            exclusive=True,
        )
    except (OSError, serial.SerialException) as exc:
        raise UartError(f"cannot open {port}: {exc}") from exc


def read_for(serial_port: serial.Serial, duration: float) -> bytes:
    deadline = time.monotonic() + duration
    received = bytearray()
    while time.monotonic() < deadline:
        chunk = serial_port.read(4096)
        if chunk:
            received.extend(chunk)
    return bytes(received)


def classify_console(data: bytes) -> str:
    text = data.decode("utf-8", errors="replace")
    lowered = text.lower()
    if "password:" in lowered:
        return "password-prompt"
    if "login:" in lowered:
        return "login-prompt"
    if re.search(r"(?:^|[\r\n])[^\r\n]*[#$>]\s*$", text):
        return "shell-prompt"
    if data:
        return "output-received"
    return "no-response"


def write_line(serial_port: serial.Serial, value: str | bytes = b"") -> None:
    payload = value.encode("utf-8") if isinstance(value, str) else value
    serial_port.write(payload + b"\r")
    serial_port.flush()


def wait_for_console_state(
    serial_port: serial.Serial,
    accepted: set[str],
    timeout: float,
) -> tuple[str, bytes]:
    deadline = time.monotonic() + timeout
    received = bytearray()
    while time.monotonic() < deadline:
        chunk = serial_port.read(4096)
        if chunk:
            received.extend(chunk)
            state = classify_console(bytes(received))
            if state in accepted:
                return state, bytes(received)
    return classify_console(bytes(received)), bytes(received)


def login_console(
    serial_port: serial.Serial,
    username: str,
    password: str,
    timeout: float,
) -> bytes:
    """Wake a getty, authenticate, and return the non-secret transcript."""

    if not username or "\r" in username or "\n" in username:
        raise UartError("username must be a non-empty single line")
    if "\r" in password or "\n" in password:
        raise UartError("password must be a single line")

    serial_port.reset_input_buffer()
    write_line(serial_port)
    state, transcript = wait_for_console_state(
        serial_port, {"login-prompt", "password-prompt", "shell-prompt"}, timeout
    )
    if state == "shell-prompt":
        return transcript

    # A previous abandoned session can leave getty at Password:. Submit an
    # empty password so that we restart from a known login prompt.
    if state == "password-prompt":
        write_line(serial_port)
        state, extra = wait_for_console_state(
            serial_port, {"login-prompt", "shell-prompt"}, timeout
        )
        transcript += extra
    if state != "login-prompt":
        raise UartError(f"did not receive a login prompt (state={state})")

    write_line(serial_port, username)
    state, extra = wait_for_console_state(
        serial_port, {"password-prompt", "shell-prompt", "login-prompt"}, timeout
    )
    transcript += extra
    if state == "shell-prompt":
        return transcript
    if state != "password-prompt":
        raise UartError(f"did not receive a password prompt (state={state})")

    # Linux getty disables echo for the password. Never include it in an
    # exception, transcript, command line, or log message.
    write_line(serial_port, password)
    state, extra = wait_for_console_state(
        serial_port, {"shell-prompt", "login-prompt", "password-prompt"}, timeout
    )
    transcript += extra
    if state != "shell-prompt":
        if state in {"login-prompt", "password-prompt"}:
            raise UartError("UART login failed; check the username and password")
        raise UartError(f"login did not reach a shell prompt (state={state})")
    return transcript


def extract_command_result(data: bytes, begin: str, end: str) -> CommandResult:
    text = data.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    start_index = text.find(begin)
    if start_index < 0:
        raise UartError("remote command start marker was not received")
    output_start = start_index + len(begin)
    match = re.search(rf"{re.escape(end)}:(\d+)", text[output_start:])
    if match is None:
        raise UartError("remote command completion marker was not received")
    output_end = output_start + match.start()
    output = text[output_start:output_end].strip("\n")
    return CommandResult(stdout=output, returncode=int(match.group(1)))


def disable_terminal_echo(serial_port: serial.Serial, timeout: float) -> None:
    write_line(serial_port, "stty -echo")
    state, _ = wait_for_console_state(serial_port, {"shell-prompt"}, timeout)
    if state != "shell-prompt":
        raise UartError("shell stopped responding while disabling terminal echo")
    serial_port.reset_input_buffer()


def restore_terminal_echo(serial_port: serial.Serial) -> None:
    write_line(serial_port, "stty echo")


def authenticate_sudo(
    serial_port: serial.Serial,
    password: str,
    timeout: float,
) -> None:
    """Refresh sudo credentials without placing the password in a command."""

    nonce = secrets.token_hex(8)
    prompt = f"__KR260_SUDO_PROMPT_{nonce}__"
    done = f"__KR260_SUDO_DONE_{nonce}__"
    write_line(
        serial_port,
        f"sudo -S -p '{prompt}' -v; kr260_sudo_rc=$?; "
        f"printf '\\n{done}:%s\\n' \"$kr260_sudo_rc\"",
    )
    deadline = time.monotonic() + timeout
    received = bytearray()
    password_sent = False
    done_pattern = re.compile(re.escape(done).encode("ascii") + rb":(\d+)")
    while time.monotonic() < deadline:
        chunk = serial_port.read(4096)
        if not chunk:
            continue
        received.extend(chunk)
        if prompt.encode("ascii") in received and not password_sent:
            write_line(serial_port, password)
            password_sent = True
        match = done_pattern.search(received)
        if match:
            if int(match.group(1)) != 0:
                raise UartError("sudo authentication failed")
            serial_port.reset_input_buffer()
            return
    raise UartError(f"sudo authentication timed out after {timeout:g} seconds")


def execute_remote_command(
    serial_port: serial.Serial,
    command: str,
    timeout: float,
    run_as_root: bool = False,
    preserve_pynq_env: bool = False,
) -> CommandResult:
    if not command:
        raise UartError("remote command must not be empty")

    nonce = secrets.token_hex(8)
    begin = f"__KR260_BEGIN_{nonce}__"
    end = f"__KR260_END_{nonce}__"
    shell_command = f"sh -c {shlex.quote(command)}"
    if run_as_root:
        sudo_command = "sudo -n"
        if preserve_pynq_env:
            sudo_command += (
                " --preserve-env=BOARD,XILINX_XRT,"
                "PYNQ_JUPYTER_NOTEBOOKS,VIRTUAL_ENV"
            )
        shell_command = f"{sudo_command} {shell_command}"
    remote_line = (
        f"printf '\\n{begin}\\n'; "
        f"{shell_command}; kr260_rc=$?; "
        f"printf '\\n{end}:%s\\n' \"$kr260_rc\""
    )
    write_line(serial_port, remote_line)
    deadline = time.monotonic() + timeout
    received = bytearray()
    end_pattern = re.compile(rb"__KR260_END_[0-9a-f]+__:\d+")
    while time.monotonic() < deadline:
        chunk = serial_port.read(4096)
        if chunk:
            received.extend(chunk)
            if end_pattern.search(received):
                return extract_command_result(bytes(received), begin, end)
    raise UartError(f"remote command timed out after {timeout:g} seconds")


def command_list(_: argparse.Namespace) -> int:
    ports = discover_ports()
    if not ports:
        print("No Xilinx KR Carrier Card serial interfaces found.")
        return 1
    for port in ports:
        role = "Linux console candidate" if port.is_console_candidate else "FTDI auxiliary"
        serial_number = port.serial_number or "unknown"
        print(
            f"{port.path}\tinterface={port.interface or 'unknown'}\t"
            f"serial={serial_number}\t{role}"
        )
    return 0


def command_probe(args: argparse.Namespace) -> int:
    port = select_console_port(args.port)
    with open_serial(port, args.baud, timeout=0.1) as serial_port:
        serial_port.reset_input_buffer()
        serial_port.write(b"\r\n")
        serial_port.flush()
        data = read_for(serial_port, args.seconds)
    print(f"port={port}")
    print(f"state={classify_console(data)}")
    print(f"received_bytes={len(data)}")
    if data:
        print("--- console output ---")
        sys.stdout.flush()
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
        if not data.endswith(b"\n"):
            print()
    return 0 if data else 1


def command_monitor(args: argparse.Namespace) -> int:
    port = select_console_port(args.port)
    deadline = None if args.seconds == 0 else time.monotonic() + args.seconds
    try:
        with open_serial(port, args.baud, timeout=0.1) as serial_port:
            if not args.no_wake:
                write_line(serial_port)
            while deadline is None or time.monotonic() < deadline:
                data = serial_port.read(4096)
                if data:
                    sys.stdout.buffer.write(data)
                    sys.stdout.buffer.flush()
    except KeyboardInterrupt:
        print("\n[kr260-uart] monitor stopped", file=sys.stderr)
    return 0


def command_send(args: argparse.Namespace) -> int:
    port = select_console_port(args.port)
    with open_serial(port, args.baud, timeout=0.1) as serial_port:
        serial_port.reset_input_buffer()
        if args.no_newline:
            serial_port.write(args.text.encode("utf-8"))
            serial_port.flush()
        else:
            write_line(serial_port, args.text)
        data = read_for(serial_port, args.seconds)
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()
    return 0


def command_exec(args: argparse.Namespace) -> int:
    port = select_console_port(args.port)
    username = args.username
    password = ""
    if not args.no_login:
        if not username:
            if not sys.stdin.isatty():
                raise UartError("--username is required when stdin is not interactive")
            username = input("KR260 username: ").strip()
    if not args.no_login or args.sudo:
        if args.password_stdin:
            password = sys.stdin.readline().rstrip("\r\n")
        else:
            if not sys.stdin.isatty():
                raise UartError(
                    "a terminal is required for hidden password input; use --password-stdin"
                )
            password = getpass.getpass("KR260 password: ")

    with open_serial(port, args.baud, timeout=0.1) as serial_port:
        if args.no_login:
            serial_port.reset_input_buffer()
            write_line(serial_port)
            state, _ = wait_for_console_state(
                serial_port, {"shell-prompt", "login-prompt", "password-prompt"}, args.timeout
            )
            if state != "shell-prompt":
                raise UartError(
                    f"an authenticated shell is required for --no-login (state={state})"
                )
        else:
            login_console(serial_port, username, password, args.timeout)
        echo_disabled = False
        try:
            # With echo disabled, framing and sudo prompt markers can only be
            # received from the remote program, never from the typed command.
            disable_terminal_echo(serial_port, args.timeout)
            echo_disabled = True
            if args.sudo:
                authenticate_sudo(serial_port, password, args.timeout)
            result = execute_remote_command(
                serial_port,
                args.remote_command,
                args.timeout,
                run_as_root=args.sudo,
                preserve_pynq_env=args.preserve_pynq_env,
            )
        except Exception:
            if echo_disabled:
                # Interrupt a command that may still own the foreground TTY
                # before trying to restore terminal echo.
                serial_port.write(b"\x03")
                serial_port.flush()
                time.sleep(0.1)
            raise
        finally:
            if echo_disabled:
                try:
                    restore_terminal_echo(serial_port)
                except (OSError, serial.SerialException):
                    pass

    if result.stdout:
        print(result.stdout)
    print(f"[kr260-uart] remote return code: {result.returncode}", file=sys.stderr)
    return result.returncode


def command_console(args: argparse.Namespace) -> int:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise UartError("console mode requires an interactive terminal")

    port = select_console_port(args.port)
    print(
        f"Opening {port} at {args.baud} baud. Press Ctrl-] to disconnect; "
        "Ctrl-C is forwarded to the board.",
        file=sys.stderr,
    )
    with open_serial(port, args.baud, timeout=0) as serial_port:
        input_fd = sys.stdin.fileno()
        output_fd = sys.stdout.fileno()
        original = termios.tcgetattr(input_fd)
        try:
            tty.setraw(input_fd)
            serial_port.write(b"\r\n")
            serial_port.flush()
            while True:
                readable, _, _ = select.select(
                    [input_fd, serial_port.fileno()], [], [], 0.25
                )
                if serial_port.fileno() in readable:
                    data = serial_port.read(4096)
                    if data:
                        os.write(output_fd, data)
                if input_fd in readable:
                    data = os.read(input_fd, 4096)
                    if not data:
                        return 0
                    if b"\x1d" in data:
                        before_exit = data.split(b"\x1d", 1)[0]
                        if before_exit:
                            serial_port.write(before_exit)
                            serial_port.flush()
                        return 0
                    serial_port.write(data)
                    serial_port.flush()
        finally:
            termios.tcsetattr(input_fd, termios.TCSADRAIN, original)
            print("\nDisconnected.", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--port",
        help="serial device; default auto-detects the KR carrier if01 by-id link",
    )
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD)
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="list KR carrier FTDI interfaces")
    list_parser.set_defaults(handler=command_list)

    probe_parser = subparsers.add_parser("probe", help="send Enter and classify the reply")
    probe_parser.add_argument("--seconds", type=float, default=2.0)
    probe_parser.set_defaults(handler=command_probe)

    monitor_parser = subparsers.add_parser(
        "monitor", help="continuously print UART output without a GUI"
    )
    monitor_parser.add_argument(
        "--seconds", type=float, default=0.0, help="0 means until Ctrl-C"
    )
    monitor_parser.add_argument(
        "--no-wake", action="store_true", help="do not send Enter when opening the port"
    )
    monitor_parser.set_defaults(handler=command_monitor)

    send_parser = subparsers.add_parser(
        "send", help="send text and print the raw UART response"
    )
    send_parser.add_argument("text")
    send_parser.add_argument("--seconds", type=float, default=2.0)
    send_parser.add_argument("--no-newline", action="store_true")
    send_parser.set_defaults(handler=command_send)

    exec_parser = subparsers.add_parser(
        "exec", help="log in, execute one shell command, and return its status"
    )
    exec_parser.add_argument("remote_command")
    exec_parser.add_argument("--username")
    exec_parser.add_argument(
        "--password-stdin",
        action="store_true",
        help="read one password line from stdin instead of prompting",
    )
    exec_parser.add_argument(
        "--no-login",
        action="store_true",
        help="use an already authenticated shell and do not request credentials",
    )
    exec_parser.add_argument(
        "--sudo",
        action="store_true",
        help="authenticate sudo over stdin and execute the command as root",
    )
    exec_parser.add_argument(
        "--preserve-pynq-env",
        action="store_true",
        help="preserve only the board's PYNQ/XRT variables through sudo",
    )
    exec_parser.add_argument("--timeout", type=float, default=15.0)
    exec_parser.set_defaults(handler=command_exec)

    console_parser = subparsers.add_parser("console", help="open an interactive serial console")
    console_parser.set_defaults(handler=command_console)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.baud <= 0:
        print("error: --baud must be positive", file=sys.stderr)
        return 2
    seconds = getattr(args, "seconds", 1.0)
    if seconds < 0 or (args.command in {"probe", "send"} and seconds == 0):
        print("error: --seconds must be nonnegative and nonzero for probe/send", file=sys.stderr)
        return 2
    if getattr(args, "timeout", 1.0) <= 0:
        print("error: --timeout must be positive", file=sys.stderr)
        return 2
    if getattr(args, "preserve_pynq_env", False) and not getattr(args, "sudo", False):
        print("error: --preserve-pynq-env requires --sudo", file=sys.stderr)
        return 2
    try:
        return int(args.handler(args))
    except (UartError, OSError, serial.SerialException, KeyboardInterrupt) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
