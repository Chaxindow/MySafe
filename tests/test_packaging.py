"""The packaged-app helpers: --self-check and copying MySafe.exe next to a USB copy."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from mysafe import self_check  # noqa: E402
from mysafe.app import copy_program_to  # noqa: E402


def test_self_check_passes_from_source(qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    report = tmp_path / "report.txt"
    assert self_check.run(report) == 0
    text = report.read_text(encoding="utf-8")
    assert "RESULT: all checks passed" in text
    assert sum(line.startswith("OK ") for line in text.splitlines()) == len(self_check.CHECKS)


def test_self_check_reports_failures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken() -> str:
        raise FileNotFoundError("0001_initial.sql")

    monkeypatch.setattr(self_check, "CHECKS", [("bundled migrations", broken)])
    report = tmp_path / "report.txt"
    assert self_check.run(report) == 1
    assert "FAIL  bundled migrations: FileNotFoundError: 0001_initial.sql" in (
        report.read_text(encoding="utf-8")
    )


def test_program_is_not_copied_when_running_from_source(tmp_path: Path) -> None:
    assert copy_program_to(tmp_path) is None
    assert list(tmp_path.iterdir()) == []


def test_packaged_program_is_copied_to_the_stick(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    program = tmp_path / "app" / "MySafe.exe"
    program.parent.mkdir()
    program.write_bytes(b"MZ fake program")
    stick = tmp_path / "stick"
    stick.mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(program))
    copied = copy_program_to(stick)
    assert copied == stick / "MySafe.exe"
    assert copied.read_bytes() == b"MZ fake program"
    # Running from the stick itself: nothing to copy.
    monkeypatch.setattr(sys, "executable", str(copied))
    assert copy_program_to(stick) == copied
