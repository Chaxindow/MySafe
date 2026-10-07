"""Enforce the layer rules described in docs/ARCHITECTURE.md.

Each module's imports are read with `ast` (no code is executed), so these tests run
even where PySide6 is not installed.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parent.parent / "mysafe"


def _module_name(path: Path) -> str:
    parts = path.relative_to(PACKAGE_ROOT.parent).with_suffix("").parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


MODULES: dict[str, set[str]] = {
    _module_name(p): _imports(p) for p in sorted(PACKAGE_ROOT.rglob("*.py"))
}


def _in(module: str, package: str) -> bool:
    return module == package or module.startswith(package + ".")


def _violations(source_pkg: str, forbidden: list[str]) -> list[str]:
    return [
        f"{mod} imports {imp}"
        for mod, imps in MODULES.items()
        if _in(mod, source_pkg)
        for imp in imps
        if any(_in(imp, f) for f in forbidden)
    ]


def test_modules_were_found() -> None:
    assert "mysafe.models" in MODULES
    assert "mysafe.db.repository" in MODULES


def test_models_depend_on_nothing_internal() -> None:
    assert _violations("mysafe.models", ["mysafe"]) == []


@pytest.mark.parametrize("package", ["mysafe.db", "mysafe.services", "mysafe.models"])
def test_core_layers_do_not_know_about_qt_or_ui(package: str) -> None:
    assert _violations(package, ["PySide6", "mysafe.ui", "mysafe.app"]) == []


def test_only_db_layer_uses_sqlite() -> None:
    offenders = [
        f"{mod} imports sqlite3"
        for mod, imps in MODULES.items()
        if "sqlite3" in imps and not _in(mod, "mysafe.db")
    ]
    assert offenders == []


def test_db_and_services_are_independent() -> None:
    assert _violations("mysafe.db", ["mysafe.services"]) == []
    assert _violations("mysafe.services", ["mysafe.db"]) == []


def test_ui_does_not_import_app_entry_point() -> None:
    assert _violations("mysafe.ui", ["mysafe.app", "mysafe.demo"]) == []


def test_only_controller_talks_to_the_database() -> None:
    offenders = [
        f"{mod} imports {imp}"
        for mod, imps in MODULES.items()
        if _in(mod, "mysafe.ui") and mod != "mysafe.ui.controller"
        for imp in imps
        if _in(imp, "mysafe.db")
    ]
    assert offenders == []
