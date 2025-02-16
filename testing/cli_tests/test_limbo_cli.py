#!/usr/bin/env python3
import os
import select
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


PIPE_BUF = 4096


@dataclass
class ShellConfig:
    sqlite_exec: str = os.getenv("LIMBO_TARGET", "./target/debug/limbo")
    sqlite_flags: List[str] = field(
        default_factory=lambda: os.getenv("SQLITE_FLAGS", "-q").split()
    )
    cwd = os.getcwd()
    test_dir: Path = field(default_factory=lambda: Path("testing"))
    py_folder: Path = field(default_factory=lambda: Path("cli_tests"))
    test_files: Path = field(default_factory=lambda: Path("test_files"))


class LimboShell:
    def __init__(self, config: ShellConfig, init_commands: Optional[str] = None):
        self.config = config
        self.pipe = self._start_repl(init_commands)

    def _start_repl(self, init_commands: Optional[str]) -> subprocess.Popen:
        pipe = subprocess.Popen(
            [self.config.sqlite_exec, *self.config.sqlite_flags],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        if init_commands and pipe.stdin is not None:
            pipe.stdin.write((init_commands + "\n").encode())
            pipe.stdin.flush()
        return pipe

    def get_test_filepath(self) -> Path:
        return self.config.test_dir / "limbo_output.txt"

    def execute(self, sql: str) -> str:
        end_marker = "END_OF_RESULT"
        self._write_to_pipe(sql)

        # If we're redirecting output, return so test's don't hang
        if sql.strip().startswith(".output"):
            return ""
        self._write_to_pipe(f"SELECT '{end_marker}';")
        output = ""
        while True:
            ready, _, errors = select.select(
                [self.pipe.stdout, self.pipe.stderr],
                [],
                [self.pipe.stdout, self.pipe.stderr],
            )
            ready_or_errors = set(ready + errors)
            if self.pipe.stderr in ready_or_errors:
                self._handle_error()
            if self.pipe.stdout in ready_or_errors:
                fragment = self.pipe.stdout.read(PIPE_BUF).decode()
                output += fragment
                if output.rstrip().endswith(end_marker):
                    return self._clean_output(output, end_marker)

    def _write_to_pipe(self, command: str) -> None:
        if not self.pipe.stdin:
            raise RuntimeError("Failed to start Limbo REPL")
        self.pipe.stdin.write((command + "\n").encode())
        self.pipe.stdin.flush()

    def _handle_error(self) -> None:
        while True:
            ready, _, errors = select.select(
                [self.pipe.stderr], [], [self.pipe.stderr], 0
            )
            if not (ready + errors):
                break
            error_output = self.pipe.stderr.read(PIPE_BUF).decode()
            print(error_output, end="")
        raise RuntimeError("Error encountered in Limbo shell.")

    @staticmethod
    def _clean_output(output: str, marker: str) -> str:
        output = output.rstrip().removesuffix(marker)
        lines = [line.strip() for line in output.split("\n") if line]
        return "\n".join(lines)

    def quit(self) -> None:
        self._write_to_pipe(".quit")
        self.pipe.terminate()


class TestLimboShell:
    def __init__(
        self, init_commands: Optional[str] = None, init_blobs_table: bool = False
    ):
        self.config = ShellConfig()
        if init_commands is None:
            # Default initialization
            init_commands = """
.open :memory:
CREATE TABLE users (id INTEGER PRIMARY KEY, first_name TEXT, last_name TEXT, age INTEGER);
CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT, price INTEGER);
INSERT INTO users VALUES (1, 'Alice', 'Smith', 30), (2, 'Bob', 'Johnson', 25),
                         (3, 'Charlie', 'Brown', 66), (4, 'David', 'Nichols', 70);
INSERT INTO products VALUES (1, 'Hat', 19.99), (2, 'Shirt', 29.99),
                            (3, 'Shorts', 39.99), (4, 'Dress', 49.99);
            """
            if init_blobs_table:
                init_commands += """
CREATE TABLE t (x1, x2, x3, x4);
INSERT INTO t VALUES (zeroblob(1024 - 1), zeroblob(1024 - 2), zeroblob(1024 - 3), zeroblob(1024 - 4));"""

            init_commands += "\n.nullvalue LIMBO"
        self.shell = LimboShell(self.config, init_commands)

    def quit(self):
        self.shell.quit()

    def run_test(self, name: str, sql: str, expected: str) -> None:
        print(f"Running test: {name}")
        actual = self.shell.execute(sql)
        assert actual == expected, (
            f"Test failed: {name}\n"
            f"SQL: {sql}\n"
            f"Expected:\n{repr(expected)}\n"
            f"Actual:\n{repr(actual)}"
        )

    def execute_dot(self, dot_command: str) -> None:
        self.shell._write_to_pipe(dot_command)
