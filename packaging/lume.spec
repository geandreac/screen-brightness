# PyInstaller: gera dist/Lume/Lume.exe (pasta “onedir”, inicia mais rápido que “onefile”).
# Uso:  pyinstaller packaging/lume.spec --noconfirm
from pathlib import Path

ROOT = Path(SPECPATH).parent

a = Analysis(
    [str(ROOT / "packaging" / "lume_entry.py")],
    pathex=[str(ROOT / "src")],
    datas=[(str(ROOT / "src" / "lume" / "assets" / "fonts"), "lume/assets/fonts")],
    hiddenimports=["lume.platform.windows", "lume.platform.autostart"],
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQml",
              "PySide6.QtQuick", "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtPdf"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Lume",
    icon=str(ROOT / "assets" / "lume.ico"),
    console=False,  # app de janela: sem console preto
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Lume", upx=False)
