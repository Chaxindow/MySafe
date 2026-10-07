from __future__ import annotations

import sys
from pathlib import Path

import pytest

from mysafe import paths


@pytest.fixture
def frozen_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Pretend MySafe runs as a packaged exe from `tmp_path` (e.g. a USB stick)."""
    exe = tmp_path / "MySafe.exe"
    exe.write_text("")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.delenv(paths.DATA_DIR_ENV, raising=False)
    return tmp_path


def test_env_override_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(paths.DATA_DIR_ENV, str(tmp_path / "custom"))
    assert paths.data_dir() == tmp_path / "custom"
    assert not paths.is_portable()


def test_running_from_source_is_never_portable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert paths.app_dir() is None
    assert paths.portable_dir() is None


def test_portable_folder_next_to_exe_is_used(frozen_app: Path) -> None:
    (frozen_app / paths.PORTABLE_DIR_NAME).mkdir()
    assert paths.is_portable()
    assert paths.data_dir() == frozen_app / paths.PORTABLE_DIR_NAME
    assert paths.db_path().parent == frozen_app / paths.PORTABLE_DIR_NAME


def test_without_portable_folder_uses_user_folder(
    frozen_app: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = frozen_app / "appdata"
    monkeypatch.setattr(paths, "user_data_dir", lambda *a, **k: str(user))
    assert not paths.is_portable()
    assert paths.data_dir() == user


def test_portable_can_be_forced_for_testing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(paths.PORTABLE_ENV, "1")
    assert paths.is_portable()
