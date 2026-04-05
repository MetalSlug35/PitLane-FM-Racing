import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


GAME_KEY = "AMS2"
APP_NAME = "AMS2 PitLane FM"
APP_EXE_NAME = "AMS2_PitLane_FM.exe"
CONFIG_EXE_NAME = "AMS2_Configurateur.exe"
SETUP_EXE_NAME = "AMS2_PitLane_FM_Setup.exe"
ICON_PNG_NAME = "AMS2_PitLane_FM_icon.png"
ICON_ICO_NAME = "AMS2_PitLane_FM_icon.ico"

THIS_DIR = Path(__file__).resolve().parent
RESSOURCE = THIS_DIR / "ressource"
PROJET_ROOT = THIS_DIR.parent.parent
BLOC11_GAME = PROJET_ROOT / "Bloc11" / GAME_KEY
BLOC11_SHARED = PROJET_ROOT / "Bloc11" / "ressource"
DIST_DIR = PROJET_ROOT / "dist" / GAME_KEY
BUILD_DIR = PROJET_ROOT / "build" / GAME_KEY
APP_WORK_DIR = BUILD_DIR / "app"
CONFIG_WORK_DIR = BUILD_DIR / "config"
OUTPUT_DIR = THIS_DIR / "output"
APP_DIST_DIR = DIST_DIR / "AMS2_PitLane_FM"
CONFIG_DIST_DIR = DIST_DIR / "AMS2_Configurateur"

SPEC_APP = RESSOURCE / "AMS2_PitLane_FM.spec"
SPEC_CONFIG = RESSOURCE / "AMS2_Configurateur.spec"
ISS_FILE = RESSOURCE / "AMS2_PitLane_FM.iss"
ICON_PNG = BLOC11_SHARED / ICON_PNG_NAME
ICON_ICO = BLOC11_GAME / ICON_ICO_NAME


def titre(texte: str) -> None:
    print(f"\n{'=' * 72}")
    print(f"  {texte}")
    print(f"{'=' * 72}")


def info(label: str, value: Path | str) -> None:
    print(f"  {label:<14}: {value}")


def executer(cmd: list[str], label: str, cwd: Path = PROJET_ROOT) -> None:
    titre(label)
    print("  Commande      :", " ".join(str(part) for part in cmd))
    result = subprocess.run(cmd, cwd=str(cwd))
    if result.returncode != 0:
        print(f"\n[ERREUR] {label} - code retour {result.returncode}")
        sys.exit(result.returncode)
    print(f"[OK] {label}")


def verifier_fichier(path: Path, role: str) -> None:
    if not path.exists():
        print(f"[ERREUR] Fichier manquant pour {role}: {path}")
        sys.exit(1)


def trouver_iscc() -> Path:
    candidats = [
        os.environ.get("ISCC_PATH"),
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
        str(Path.home() / "AppData" / "Local" / "Programs" / "Inno Setup 6" / "ISCC.exe"),
        r"C:\Program Files (x86)\Inno Setup 5\ISCC.exe",
    ]
    for candidat in candidats:
        if not candidat:
            continue
        path = Path(candidat)
        if path.exists():
            return path
    print("[ERREUR] ISCC.exe introuvable.")
    print("  Installez Inno Setup 6 ou definissez la variable ISCC_PATH.")
    sys.exit(1)


def verifier_pyinstaller() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--version"],
        cwd=str(PROJET_ROOT),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("[ERREUR] PyInstaller n'est pas disponible dans cet environnement Python.")
        sys.exit(result.returncode or 1)
    version = (result.stdout or result.stderr).strip()
    print(f"  PyInstaller   : {version}")


def preparer_dossiers() -> None:
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    APP_WORK_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_WORK_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def regenerer_icone_multi_resolution() -> None:
    verifier_fichier(ICON_PNG, "icone source PNG")
    try:
        from PIL import Image
    except Exception as exc:
        print(f"[ERREUR] Pillow est requis pour regenerer l'icone: {exc}")
        sys.exit(1)

    titre("Regeneration icone multi-resolution")
    sizes = [
        (16, 16),
        (20, 20),
        (24, 24),
        (32, 32),
        (40, 40),
        (48, 48),
        (64, 64),
        (72, 72),
        (96, 96),
        (128, 128),
        (256, 256),
    ]
    with Image.open(ICON_PNG).convert("RGBA") as image:
        ICON_ICO.parent.mkdir(parents=True, exist_ok=True)
        image.save(ICON_ICO, format="ICO", sizes=sizes)
    print(f"[OK] Icone regeneree : {ICON_ICO}")


def compiler_pyinstaller(spec_path: Path, work_dir: Path, label: str, expected_output: Path) -> None:
    verifier_fichier(spec_path, label)
    if work_dir.exists():
        shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    executer(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            f"--distpath={DIST_DIR}",
            f"--workpath={work_dir}",
            str(spec_path),
        ],
        label,
    )
    verifier_fichier(expected_output, f"sortie {label}")


def compiler_exe_principal() -> None:
    compiler_pyinstaller(
        SPEC_APP,
        APP_WORK_DIR,
        f"PyInstaller - {APP_NAME}.exe",
        APP_DIST_DIR / APP_EXE_NAME,
    )


def compiler_configurateur() -> None:
    compiler_pyinstaller(
        SPEC_CONFIG,
        CONFIG_WORK_DIR,
        "PyInstaller - AMS2_Configurateur.exe",
        CONFIG_DIST_DIR / CONFIG_EXE_NAME,
    )


def compiler_installeur() -> None:
    verifier_fichier(APP_DIST_DIR / APP_EXE_NAME, "exe principal avant Inno Setup")
    verifier_fichier(CONFIG_DIST_DIR / CONFIG_EXE_NAME, "configurateur avant Inno Setup")
    iscc = trouver_iscc()
    setup_path = OUTPUT_DIR / SETUP_EXE_NAME
    before_ts = time.time()
    if setup_path.exists():
        print(f"  Ancien setup    : suppression de {setup_path}")
        setup_path.unlink()
    executer([str(iscc), str(ISS_FILE)], f"Inno Setup - {APP_NAME} Setup.exe", cwd=RESSOURCE)
    verifier_fichier(setup_path, "setup Inno Setup")
    built_ts = setup_path.stat().st_mtime
    if built_ts < before_ts - 1:
        print(f"[ERREUR] Le setup trouve n'a pas ete regénéré pendant ce build : {setup_path}")
        sys.exit(1)
    print(f"[OK] Setup regenere : {setup_path} ({setup_path.stat().st_size} octets)")


def main() -> None:
    args = set(sys.argv[1:])
    exe_only = "--exe-only" in args
    iss_only = "--iss-only" in args
    skip_icon_refresh = "--skip-icon-refresh" in args

    print(f"\n{APP_NAME} - Compilation")
    info("Projet root", PROJET_ROOT)
    info("Dist", DIST_DIR)
    info("Output", OUTPUT_DIR)

    verifier_pyinstaller()
    preparer_dossiers()

    for path, role in (
        (SPEC_APP, "spec application"),
        (SPEC_CONFIG, "spec configurateur"),
        (ISS_FILE, "script Inno Setup"),
    ):
        verifier_fichier(path, role)

    if not skip_icon_refresh:
        regenerer_icone_multi_resolution()

    if iss_only:
        compiler_installeur()
    elif exe_only:
        compiler_exe_principal()
        compiler_configurateur()
    else:
        compiler_exe_principal()
        compiler_configurateur()
        compiler_installeur()

    print(f"\n[SUCCES] Compilation {APP_NAME} terminee.")
    info("Exe principal", APP_DIST_DIR / APP_EXE_NAME)
    info("Configurateur", CONFIG_DIST_DIR / CONFIG_EXE_NAME)
    if (OUTPUT_DIR / SETUP_EXE_NAME).exists():
        info("Setup", OUTPUT_DIR / SETUP_EXE_NAME)
    print()


if __name__ == "__main__":
    main()
