"""`MySafe --self-check <report file>`: prove a packaged build has everything it needs.

Runs without showing a window and without touching the user's vault: loads the bundled
files, opens a database, encrypts and re-opens a throw-away vault in a temporary folder,
and draws the icons. Writes one line per check to the report file; exit code 0 = all OK.
Used by build.bat / CI right after PyInstaller, because a missing data file only shows
up in the frozen app.
"""

from __future__ import annotations

import os
import sys
import tempfile
import traceback
from collections.abc import Callable
from pathlib import Path

from mysafe import APP_NAME, __version__


def _migrations() -> str:
    from mysafe.db.connection import load_migrations

    return f"{len(load_migrations())} migrations"


def _database() -> str:
    from mysafe.db import Repository, open_database

    repo = Repository(open_database(":memory:"))
    repo.ensure_default_categories()
    count = len(repo.list_categories())
    repo.close()
    return f"{count} default categories"


def _vault() -> str:
    from mysafe.services.crypto import KdfParams
    from mysafe.vault import Vault

    fast = KdfParams(memory_kib=8 * 1024, iterations=1, lanes=1)
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "vault.mysafe"
        vault, recovery = Vault.create(path, "self-check password", params=fast)
        vault.repo.ensure_default_categories()
        vault.lock()
        Vault.unlock(path, "self-check password").lock()
        Vault.unlock_with_recovery_key(path, recovery).lock()
    return "create / unlock / recovery key OK (AES-256-GCM + Argon2id)"


def _icons() -> str:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QGuiApplication

    from mysafe.resources import resource_path
    from mysafe.ui.icons import icon

    app = QGuiApplication.instance() or QGuiApplication([APP_NAME])
    missing = [
        name
        for name in ("icon-32.png", "icon-64.png", "icon-256.png", "mysafe.ico")
        if not resource_path(name).is_file()
    ]
    if missing:
        raise FileNotFoundError(f"missing resources: {', '.join(missing)}")
    if icon("eye", "#808080").pixmap(16, 16).isNull():
        raise RuntimeError("SVG icons could not be drawn (QtSvg missing?)")
    del app
    return "app icon files + SVG icons OK"


CHECKS: list[tuple[str, Callable[[], str]]] = [
    ("bundled migrations", _migrations),
    ("database", _database),
    ("encrypted vault", _vault),
    ("icons", _icons),
]


def run(report: Path | None) -> int:
    lines = [f"{APP_NAME} {__version__} self-check ({sys.platform}, frozen={_frozen()})"]
    failed = 0
    for name, check in CHECKS:
        try:
            lines.append(f"OK    {name}: {check()}")
        except Exception:  # noqa: BLE001 - report every failure, keep going
            failed += 1
            detail = traceback.format_exc().strip().splitlines()[-1]
            lines.append(f"FAIL  {name}: {detail}")
    lines.append("RESULT: " + ("all checks passed" if not failed else f"{failed} failed"))
    text = "\n".join(lines) + "\n"
    if report is not None:
        report.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 1 if failed else 0


def _frozen() -> bool:
    return bool(getattr(sys, "frozen", False))
