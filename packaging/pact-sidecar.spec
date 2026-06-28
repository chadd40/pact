# Build from repo root: uv run pyinstaller packaging/pact-sidecar.spec --noconfirm
import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

# SPECPATH is the directory containing this spec file (packaging/).
# Repo root is one level up.
_repo_root = os.path.dirname(SPECPATH)

datas, binaries, hiddenimports = [], [], []
for pkg in ("imagehash", "scipy", "numpy", "PIL", "pywt"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

hiddenimports += collect_submodules("uvicorn")
hiddenimports += [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
]

a = Analysis(
    [os.path.join(SPECPATH, "sidecar_entry.py")],
    pathex=[os.path.join(_repo_root, "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="pact-sidecar",
    debug=False,
    strip=False,
    upx=False,
    console=True,
)
