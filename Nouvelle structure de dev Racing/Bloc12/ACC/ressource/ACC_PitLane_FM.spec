# =============================================================================
#  ACC_PitLane_FM.spec — PyInstaller spec
#  Point d'entrée : Bloc1/ACC/ACC_lanceur.py
#  À exécuter depuis la RACINE du projet.
# =============================================================================

from pathlib import Path

block_cipher = None
PROJET_ROOT  = Path(".").resolve()
BLOC11_ACC   = PROJET_ROOT / "Bloc11" / "ACC"        # contient le .ico
BLOC11_SH    = PROJET_ROOT / "Bloc11" / "ressource"  # ressources partagées

datas = [
    (str(BLOC11_ACC / "ACC_PitLane_FM_icon.ico"),    "."),
    (str(BLOC11_SH  / "buy_me_a_coffee_logo.png"),   "."),
    (str(BLOC11_SH  / "buy_me_a_coffee_url.txt"),    "."),
    (str(BLOC11_SH  / "nexus_mod_url.txt"),          "."),
]

a = Analysis(
    [str(PROJET_ROOT / "Bloc1" / "ACC" / "ACC_lanceur.py")],
    pathex=[str(PROJET_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "miniaudio",
        "comtypes", "comtypes.client", "comtypes.automation", "comtypes.typeinfo",
        "psutil", "psutil._pswindows",
        "pyaccsharedmemory",
        "pygame", "pygame._sdl2", "pygame._sdl2.controller",
        "Bloc3.ACC.ACC_state_monitor", "Bloc3.ACC.ACC_tableau_etats",
        "Bloc4.coordinateur",
        "Bloc5.interpreteur_shortcuts",
        "Bloc6.music_player",
        "Bloc8.TTS_player",
        "Bloc9.Stop_saver",
        "Bloc10.Support",
        "tkinter", "tkinter.ttk",
        "PIL", "PIL.Image", "PIL.ImageTk",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "numpy", "scipy", "pandas", "IPython", "jupyter"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="ACC_PitLane_FM",
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
    icon=str(BLOC11_ACC / "ACC_PitLane_FM_icon.ico"),
    version=str(PROJET_ROOT / "Bloc12" / "ACC" / "ressource" / "version_info.txt"),
    manifest=str(PROJET_ROOT / "Bloc12" / "ressource" / "app.manifest"),
    uac_admin=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="ACC_PitLane_FM",
)
