# PyInstaller recipe for the single-process Windows distribution.

from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = [
    ("frontend/dist", "frontend/dist"),
    ("alembic", "alembic"),
    ("alembic.ini", "."),
]
binaries = []
hiddenimports = []
for package in ("uvicorn", "fastapi", "sqlalchemy", "alembic", "langgraph", "langgraph_checkpoint", "mcp", "tiktoken"):
    hiddenimports += collect_submodules(package)
for package in ("tiktoken",):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

a = Analysis(
    ["saraswati_launcher.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SaraswatiAgent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name="SaraswatiAgent",
)
