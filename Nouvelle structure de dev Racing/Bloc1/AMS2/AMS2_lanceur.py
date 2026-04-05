# =============================================================================
#  Bloc1 — AMS2_lanceur.py
#  Lanceur principal de AMS2 PitLane FM (Automobilista 2).
# =============================================================================

import os
import sys
import time
import multiprocessing as mp
import ctypes
import ctypes.wintypes

import pygame

import Bloc9.Stop_saver as saver
import Bloc9.Pitlane_paths as pitlane_paths
from Bloc4.coordinateur import Coordinateur
from Bloc3.AMS2.AMS2_state_monitor import find_process, get_state
from Bloc3.AMS2.AMS2_tableau_etats import POLITIQUE_MUSIQUE

APP_NAME         = "AMS2 PitLane FM"
APP_ID           = "MetalSlug.AMS2PitLaneFM"
INSTALL_DIR      = pitlane_paths.app_install_dir(APP_NAME)
CONFIG_FILE      = pitlane_paths.app_config_file(APP_NAME)
RADIO_FOLDER     = pitlane_paths.shared_radio_dir()
ICON_FILE        = "AMS2_PitLane_FM_icon.ico"
LOGO_FILE        = "buy_me_a_coffee_logo.png"
ACCENT_COLOR     = "#27ae60"
STEAM_APP_ID     = "1066890"
STEAM_LAUNCH_URI = f"steam://launch/{STEAM_APP_ID}/dialog"
DONATE_URL_FILE  = "buy_me_a_coffee_url.txt"
NEXUS_URL_FILE   = "nexus_mod_url.txt"
DONATE_FALLBACK  = "https://buymeacoffee.com/MetalSlug"
NEXUS_FALLBACK   = "https://www.nexusmods.com/profile/MetalSlug35/mods"

DELAI_ATTENTE_MAX    = 120.0
DELAI_DETECT_DIALOG  = 8.0

_user32 = ctypes.WinDLL("user32", use_last_error=True)


def _runtime_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _asset(filename: str) -> str:
    candidates = [os.path.join(_runtime_dir(), filename), os.path.join(INSTALL_DIR, filename)]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(os.path.join(meipass, filename))
    for p in candidates:
        if os.path.exists(p):
            return p
    return candidates[0]


def _read_url(filename: str, fallback: str) -> str:
    try:
        with open(_asset(filename), "r", encoding="utf-8") as f:
            raw = f.read().strip()
        if raw and not raw.startswith(("http://", "https://")):
            raw = "https://" + raw
        return raw or fallback
    except Exception:
        return fallback


def _hide_sdl_window():
    try:
        wm_info = pygame.display.get_wm_info() or {}
        hwnd = wm_info.get("window")
        if not hwnd:
            return
        # WS_EX_TOOLWINDOW retire la fenêtre de la barre des tâches et Alt+Tab
        _GWL_EXSTYLE      = -20
        _WS_EX_TOOLWINDOW = 0x00000080
        _WS_EX_APPWINDOW  = 0x00040000
        _WS_EX_NOACTIVATE = 0x08000000
        if ctypes.sizeof(ctypes.c_void_p) == ctypes.sizeof(ctypes.c_longlong):
            _get = _user32.GetWindowLongPtrW
            _set = _user32.SetWindowLongPtrW
        else:
            _get = _user32.GetWindowLongW
            _set = _user32.SetWindowLongW
        ex = int(_get(hwnd, _GWL_EXSTYLE) or 0)
        _set(hwnd, _GWL_EXSTYLE, (ex | _WS_EX_TOOLWINDOW | _WS_EX_NOACTIVATE) & ~_WS_EX_APPWINDOW)
        # SWP_FRAMECHANGED (0x0020) applique le nouveau style + déplace hors écran
        _user32.SetWindowPos(hwnd, 0, -32000, -32000, 1, 1, 0x0010 | 0x0004 | 0x0020)
    except Exception:
        pass


def _snapshot_fenetres_visibles() -> set:
    hwnds = set()
    _EnumProc = ctypes.WINFUNCTYPE(
        ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
    )
    def _cb(hwnd, _):
        if _user32.IsWindowVisible(hwnd):
            hwnds.add(hwnd)
        return True
    _user32.EnumWindows(_EnumProc(_cb), 0)
    return hwnds


def _lancer_steam() -> set:
    """Lance le dialog Steam de sélection du mode de jeu.

    Retourne un snapshot des fenêtres visibles AVANT le lancement.
    """
    snapshot = _snapshot_fenetres_visibles()
    prev = os.environ.pop("SDL_VIDEODRIVER", None)
    try:
        os.startfile(STEAM_LAUNCH_URI)
    except Exception:
        pass
    finally:
        if prev is not None:
            os.environ["SDL_VIDEODRIVER"] = prev
    return snapshot


def _attendre_jeu(snapshot_avant: set, timeout: float = DELAI_ATTENTE_MAX):
    """Attend le processus du jeu. Détecte l'annulation du dialog Steam.

    Une période de grâce est accordée après la fermeture du dialog pour laisser
    le temps au jeu de démarrer (Steam peut mettre ~10-20 s avant que le processus
    soit visible). Ce n'est qu'à l'expiration de cette grâce sans jeu détecté
    que la fermeture du dialog est interprétée comme une annulation.
    """
    GRACE_CANCEL    = 30.0
    debut           = time.time()
    dialog_hwnd     = None
    dialog_ferme_at = None

    while time.time() - debut < timeout:
        time.sleep(0.5)
        proc = find_process()
        if proc is not None:
            return proc

        if dialog_hwnd is None:
            nouvelles = _snapshot_fenetres_visibles() - snapshot_avant
            if nouvelles:
                dialog_hwnd = max(nouvelles)

        if dialog_hwnd and not _user32.IsWindow(dialog_hwnd):
            if dialog_ferme_at is None:
                dialog_ferme_at = time.time()
            elif time.time() - dialog_ferme_at > GRACE_CANCEL:
                return None

    return None


def main():
    if not os.environ.get("PITLANE_CONSOLE"):
        sys.stdout = open(os.devnull, "w")
        sys.stderr = open(os.devnull, "w")
        sys.stdin  = open(os.devnull, "r")

    os.environ.setdefault("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    pygame.init()
    try:
        pygame.mixer.quit()
    except Exception:
        pass
    try:
        pygame.display.set_mode((1, 1), pygame.NOFRAME)
    except Exception:
        pass
    pygame.joystick.init()

    state = saver.lire(CONFIG_FILE)
    state["music_folders"] = saver.normalize_music_folders(
        state.get("music_folders") or state.get("music_folder") or []
    )
    state["music_folder"] = state["music_folders"][0] if state["music_folders"] else ""
    state["radio_folder"] = state.get("radio_folder") or RADIO_FOLDER
    saver.incrementer_usage(state)
    saver.sauvegarder(CONFIG_FILE, state)

    snapshot_avant = _lancer_steam()
    proc = _attendre_jeu(snapshot_avant)
    if proc is None:
        pygame.quit()
        return

    cfg = dict(state)
    cfg.update({
        "config_file":      CONFIG_FILE,
        "get_proc":         find_process,
        "get_game_state":   get_state,
        "music_policy_map": POLITIQUE_MUSIQUE,
        "check_interval":   0.8,
        "app_title":        APP_NAME,
        "app_id":           APP_ID,
        "icon_path":        _asset(ICON_FILE),
        "logo_path":        _asset(LOGO_FILE),
        "accent_color":     ACCENT_COLOR,
        "donate_url":       _read_url(DONATE_URL_FILE, DONATE_FALLBACK),
        "nexus_url":        _read_url(NEXUS_URL_FILE,  NEXUS_FALLBACK),
        "donation_trigger": 10,
        "on_exit_hook":     lambda: pygame.quit(),
    })

    Coordinateur(cfg).demarrer()


if __name__ == "__main__":
    mp.freeze_support()
    main()
