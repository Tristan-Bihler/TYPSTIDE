# PyInstaller spec for the Windows app: a one-folder, windowed build.
# Built by scripts/build_windows.py; the installer (installer.iss) packs the folder.
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent  # noqa: F821 - defined by PyInstaller
ICON = ROOT / "packaging" / "typst-writer.ico"

datas = [
    (str(ROOT / "config.toml"), "."),
    (str(ROOT / "snippets.toml"), "."),
    (str(ROOT / "frontend" / "dist"), "frontend/dist"),
    (str(ICON), "packaging"),
]
# uvicorn chooses its protocol and loop implementations at runtime.
hiddenimports = collect_submodules("uvicorn") + collect_submodules("typst_writer")

a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT / "backend" / "src")],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest", "mypy", "playwright"],
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="typst-writer",
    icon=str(ICON),
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="typst-writer", upx=False)  # noqa: F821
