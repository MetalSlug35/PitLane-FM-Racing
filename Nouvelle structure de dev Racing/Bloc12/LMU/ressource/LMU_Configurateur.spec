# =============================================================================
#  LMU_Configurateur.spec — PyInstaller spec
#  Point d'entrée : Bloc11/LMU/LMU_configurateur.py
#  À exécuter depuis la RACINE du projet.
# =============================================================================

from pathlib import Path

block_cipher = None
PROJET_ROOT  = Path(".").resolve()
BLOC11_LMU   = PROJET_ROOT / "Bloc11" / "LMU"
BLOC11_SH    = PROJET_ROOT / "Bloc11" / "ressource"

datas = [
    (str(BLOC11_LMU / "LMU_PitLane_FM_icon.ico"),    "."),
    (str(BLOC11_SH  / "LMU_PitLane_FM.png"),         "."),
    (str(BLOC11_SH  / "buy_me_a_coffee_logo.png"),   "."),
    (str(BLOC11_SH  / "buy_me_a_coffee_url.txt"),    "."),
    (str(BLOC11_SH  / "nexus_mod_url.txt"),          "."),
]
datas += [(str(path), ".") for path in sorted(BLOC11_SH.glob("*.m3u"))]
datas += [(str(path), ".") for path in sorted(BLOC11_SH.glob("*.m3u8"))]
datas += [(str(path), ".") for path in sorted(BLOC11_SH.glob("*.pls"))]

a = Analysis(
    [str(PROJET_ROOT / "Bloc11" / "LMU" / "LMU_configurateur.py")],
    pathex=[str(PROJET_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "tkinter", "tkinter.ttk", "tkinter.filedialog",
        "PIL", "PIL.Image", "PIL.ImageTk",
        "psutil", "psutil._pswindows",
        "pygame", "pygame._sdl2",
        "Bloc9.Stop_saver",
        "comtypes", "comtypes.client",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "numpy", "scipy", "pandas"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="LMU_Configurateur",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(BLOC11_LMU / "LMU_PitLane_FM_icon.ico"),
    version=str(PROJET_ROOT / "Bloc12" / "LMU" / "ressource" / "version_info.txt"),
    uac_admin=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="LMU_Configurateur",
)
