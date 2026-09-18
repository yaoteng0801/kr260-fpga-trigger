#!/usr/bin/env python3
"""Simple host-side menu and commands for the connected KR260 trigger board."""

from __future__ import annotations

import argparse
from contextlib import AbstractContextManager
import getpass
from pathlib import PurePosixPath
import shlex
import sys
import time

import serial

if __package__ in (None, ""):
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from software.kr260_uart import (
    UartError,
    authenticate_sudo,
    disable_terminal_echo,
    execute_remote_command,
    login_console,
    open_serial,
    restore_terminal_echo,
    select_console_port,
)


DEFAULT_USERNAME = "ubuntu"
DEFAULT_BAUD = 115_200
DEFAULT_TIMEOUT = 120.0
BOARD_APP = PurePosixPath("/home/ubuntu/notebooks/Trigger/kr260_trigger_app")
PYNQ_PYTHON = PurePosixPath("/usr/local/share/pynq-venv/bin/python3")
HDF5_FILE = PurePosixPath("../Trigger_food_Data.h5")
TRIGGER_BIT = PurePosixPath("deploy/kr260_trigger.bit")
LOOPBACK_BIT = PurePosixPath("deploy/kr260_loopback.bit")


def _q(value: object) -> str:
    return shlex.quote(str(value))


def _in_app(command: str) -> str:
    return f"cd {_q(BOARD_APP)} && {command}"


def info_command() -> str:
    script = (
        "import os,sys,pynq; from pynq import Device,Clocks; "
        "print('python=',sys.executable); print('pynq=',pynq.__version__); "
        "print('board=',os.environ.get('BOARD')); "
        "print('device=',Device.active_device); print('fclk0_mhz=',Clocks.fclk0_mhz)"
    )
    return (
        "printf '===SYSTEM===\\n'; uname -a; "
        "printf '===OS===\\n'; sed -n '1,8p' /etc/os-release; "
        "printf '===PYNQ===\\n'; "
        f"{_q(PYNQ_PYTHON)} -c {_q(script)}; "
        "printf '===FPGA===\\n'; cat /sys/class/fpga_manager/fpga0/state"
    )


def loopback_command(events: int = 4097) -> str:
    return _in_app(
        f"{_q(PYNQ_PYTHON)} software/loopback_test.py "
        f"--events {events} --backend pynq --bitstream {_q(LOOPBACK_BIT)} --timeout 10"
    )


def deterministic_command() -> str:
    return _in_app(
        f"{_q(PYNQ_PYTHON)} software/deterministic_trigger_test.py "
        f"--backend pynq --bitstream {_q(TRIGGER_BIT)} --timeout 10"
    )


def hdf5_command(
    sample: str = "bkg",
    start: int = 0,
    count: int = 20_000,
    chunk_size: int = 20_000,
    report: str | None = None,
) -> str:
    command = (
        f"{_q(PYNQ_PYTHON)} software/kr260_trigger.py {_q(HDF5_FILE)} "
        f"--sample {_q(sample)} --start {start} --count {count} "
        f"--chunk-size {chunk_size} --backend pynq "
        f"--bitstream {_q(TRIGGER_BIT)} --timeout 10"
    )
    if report:
        command += f" --json-report {_q(report)}"
    return _in_app(command)


def multichunk_command() -> str:
    return hdf5_command(
        start=1_640_000,
        count=22_241,
        chunk_size=10_000,
        report="reports/board_pynq_multichunk.json",
    )


class BoardSession(AbstractContextManager["BoardSession"]):
    def __init__(
        self,
        username: str,
        password: str,
        port: str | None,
        baud: int,
        timeout: float,
    ):
        self.username = username
        self.password = password
        self.port = select_console_port(port)
        self.baud = baud
        self.timeout = timeout
        self.serial_port: serial.Serial | None = None
        self.echo_disabled = False

    def __enter__(self) -> "BoardSession":
        self.serial_port = open_serial(self.port, self.baud, timeout=0.1)
        try:
            login_console(
                self.serial_port,
                self.username,
                self.password,
                self.timeout,
            )
            disable_terminal_echo(self.serial_port, self.timeout)
            self.echo_disabled = True
            authenticate_sudo(self.serial_port, self.password, self.timeout)
            return self
        except Exception:
            self.close(interrupt=True)
            raise

    def run(self, command: str) -> int:
        if self.serial_port is None:
            raise UartError("board session is not open")
        result = execute_remote_command(
            self.serial_port,
            command,
            self.timeout,
            run_as_root=True,
            preserve_pynq_env=True,
        )
        if result.stdout:
            print(result.stdout)
        print(f"[KR260] return code: {result.returncode}", file=sys.stderr)
        return result.returncode

    def close(self, interrupt: bool = False) -> None:
        if self.serial_port is None:
            return
        try:
            if interrupt:
                self.serial_port.write(b"\x03")
                self.serial_port.flush()
                time.sleep(0.1)
            if self.echo_disabled:
                restore_terminal_echo(self.serial_port)
        except (OSError, serial.SerialException):
            pass
        finally:
            self.serial_port.close()
            self.serial_port = None
            self.echo_disabled = False

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close(interrupt=exc_type is not None)


def run_named(session: BoardSession, name: str, args: argparse.Namespace) -> int:
    if name == "info":
        return session.run(info_command())
    if name == "loopback":
        return session.run(loopback_command(args.events))
    if name == "deterministic":
        return session.run(deterministic_command())
    if name == "hdf5":
        return session.run(
            hdf5_command(
                sample=args.sample,
                start=args.start,
                count=args.count,
                chunk_size=args.chunk_size,
                report=args.report,
            )
        )
    if name == "multichunk":
        return session.run(multichunk_command())
    if name == "verify":
        steps = (
            ("Stage A: DMA loopback", loopback_command()),
            ("Stage C: deterministic trigger", deterministic_command()),
            (
                "Stage D: 20,000 HDF5 events",
                hdf5_command(report="reports/board_pynq_20k.json"),
            ),
            ("Stage D: multi-chunk tail", multichunk_command()),
        )
        for title, command in steps:
            print(f"\n===== {title} =====", flush=True)
            returncode = session.run(command)
            if returncode != 0:
                return returncode
        return 0
    raise UartError(f"unknown board action: {name}")


def interactive_menu(session: BoardSession, args: argparse.Namespace) -> int:
    choices = {
        "1": "info",
        "2": "loopback",
        "3": "deterministic",
        "4": "hdf5",
        "5": "multichunk",
        "6": "verify",
    }
    while True:
        print(
            "\nKR260 trigger menu\n"
            "  1. Board/PYNQ information\n"
            "  2. DMA loopback (4097 events)\n"
            "  3. Deterministic trigger test\n"
            "  4. HDF5 test (20,000 events)\n"
            "  5. Multi-chunk tail test\n"
            "  6. Run all verification steps\n"
            "  0. Exit"
        )
        choice = input("Select: ").strip()
        if choice == "0":
            return 0
        action = choices.get(choice)
        if action is None:
            print("Please enter 0-6.", file=sys.stderr)
            continue
        returncode = run_named(session, action, args)
        if returncode != 0:
            print(f"{action} failed with return code {returncode}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        nargs="?",
        choices=("menu", "info", "loopback", "deterministic", "hdf5", "multichunk", "verify"),
        default="menu",
    )
    parser.add_argument("--username", default=DEFAULT_USERNAME)
    parser.add_argument("--port", help="default: auto-detect KR260 if01 UART")
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    parser.add_argument("--password-stdin", action="store_true")
    parser.add_argument("--events", type=int, default=4097, help="loopback event count")
    parser.add_argument("--sample", choices=("bkg", "tt", "aa"), default="bkg")
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--count", type=int, default=20_000)
    parser.add_argument("--chunk-size", type=int, default=20_000)
    parser.add_argument("--report")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.baud <= 0 or args.timeout <= 0:
        print("error: baud and timeout must be positive", file=sys.stderr)
        return 2
    if args.events <= 0 or args.start < 0 or args.count < 0 or args.chunk_size <= 0:
        print("error: invalid event range or chunk size", file=sys.stderr)
        return 2

    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\r\n")
    else:
        if not sys.stdin.isatty():
            print("error: interactive password input requires a terminal", file=sys.stderr)
            return 2
        password = getpass.getpass(f"Password for {args.username}@KR260: ")

    try:
        with BoardSession(
            args.username,
            password,
            args.port,
            args.baud,
            args.timeout,
        ) as session:
            print(f"Connected to {session.port}", file=sys.stderr)
            if args.action == "menu":
                return interactive_menu(session, args)
            return run_named(session, args.action, args)
    except (UartError, OSError, serial.SerialException, KeyboardInterrupt) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
