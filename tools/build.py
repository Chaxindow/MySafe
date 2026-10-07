"""Build the single-file MySafe program with PyInstaller, then test the result.

    python tools/build.py          (Windows: build.bat does this inside .venv)

Output:  dist/MySafe.exe (Windows) or dist/MySafe (Linux)
         dist/MySafe.exe.sha256   checksum to publish next to the download
The built program is started once with --self-check; the build fails if any check fails.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mysafe import APP_NAME, __version__  # noqa: E402

BUILD = ROOT / "build"
DIST = ROOT / "dist"

# Big Qt parts MySafe never uses: leaving them out keeps the program much smaller.
EXCLUDES = [
    "tkinter",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickWidgets",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.QtMultimedia",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtPdf",
    "PySide6.QtBluetooth",
    "PySide6.QtPositioning",
    "PySide6.QtSql",
]


def _windows_version_file() -> Path:
    """Version info shown in the file's Properties → Details on Windows."""
    numbers = [int(part) for part in __version__.split(".")[:3] if part.isdigit()]
    numbers = (numbers + [0, 0, 0, 0])[:4]
    text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={tuple(numbers)}, prodvers={tuple(numbers)}),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('ProductName', '{APP_NAME}'),
      StringStruct('FileDescription', '{APP_NAME} password manager'),
      StringStruct('FileVersion', '{__version__}'),
      StringStruct('ProductVersion', '{__version__}'),
      StringStruct('LegalCopyright', 'GPL-3.0-or-later'),
      StringStruct('OriginalFilename', '{APP_NAME}.exe'),
    ])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
    path = BUILD / "version_info.txt"
    path.write_text(text, encoding="utf-8")
    return path


def build() -> Path:
    import PyInstaller.__main__

    BUILD.mkdir(exist_ok=True)
    sep = os.pathsep
    args = [
        str(ROOT / "mysafe" / "__main__.py"),
        "--name",
        APP_NAME,
        "--onefile",
        "--windowed",
        "--noconfirm",
        "--clean",
        "--distpath",
        str(DIST),
        "--workpath",
        str(BUILD / "pyinstaller"),
        "--specpath",
        str(BUILD),
        "--paths",
        str(ROOT),
        "--icon",
        str(ROOT / "mysafe" / "resources" / "mysafe.ico"),
        "--add-data",
        f"{ROOT / 'mysafe' / 'resources'}{sep}mysafe/resources",
        "--add-data",
        f"{ROOT / 'mysafe' / 'db' / 'migrations'}{sep}mysafe/db/migrations",
    ]
    for module in EXCLUDES:
        args += ["--exclude-module", module]
    if sys.platform == "win32":
        args += ["--version-file", str(_windows_version_file())]
    PyInstaller.__main__.run(args)
    program = DIST / (f"{APP_NAME}.exe" if sys.platform == "win32" else APP_NAME)
    if not program.is_file():
        raise SystemExit(f"Build failed: {program} was not created")
    if sys.platform.startswith("linux"):  # a clearer download name next to MySafe.exe
        program = program.replace(DIST / f"{APP_NAME}-linux-x86_64")
    return program


def self_check(program: Path) -> None:
    report = BUILD / "self-check.txt"
    report.unlink(missing_ok=True)
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    command = [str(program), "--self-check", str(report)]  # the program we just built
    result = subprocess.run(command, env=env, timeout=180)  # noqa: S603
    print(report.read_text(encoding="utf-8") if report.exists() else "(no self-check report)")
    if result.returncode != 0:
        raise SystemExit(f"Self-check of {program.name} failed (exit code {result.returncode})")


def checksum(program: Path) -> Path:
    digest = hashlib.sha256(program.read_bytes()).hexdigest()
    path = program.with_name(program.name + ".sha256")
    path.write_text(f"{digest}  {program.name}\n", encoding="utf-8")
    return path


def main() -> int:
    program = build()
    self_check(program)
    sums = checksum(program)
    size = program.stat().st_size / (1024 * 1024)
    print(f"BUILD OK: {program} ({size:.1f} MB)")
    print(f"SHA-256:  {sums.read_text(encoding='utf-8').split()[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
