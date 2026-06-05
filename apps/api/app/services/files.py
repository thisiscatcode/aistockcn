from __future__ import annotations

import json
import os
import subprocess
import time
from collections import deque
from json import JSONDecodeError
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (JSONDecodeError, OSError, UnicodeDecodeError):
        return {}


def write_json_atomic(path: Path, payload: dict[str, Any], *, ensure_ascii: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{time.monotonic_ns()}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=ensure_ascii, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def tail_file(path: Path, lines: int = 100) -> list[str]:
    if not path.exists():
        return []
    buffer: deque[str] = deque(maxlen=max(lines, 1))
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            buffer.append(line.rstrip("\n"))
    return list(buffer)


def count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        return sum(1 for _ in handle)


def run_command(args: list[str], *, timeout: int = 5) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False, ""
    output = result.stdout.strip()
    if result.returncode != 0:
        output = output or result.stderr.strip()
        return False, output
    return True, output
