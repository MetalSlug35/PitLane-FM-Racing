# =============================================================================
#  Bloc2 — VR_detecteur.py
#  Détection du mode VR (SteamVR, OpenXR, Oculus, WMR…).
#  Module universel — aucune dépendance à un jeu spécifique.
#
#  API publique :
#    configure(game_log_parser=None)    — optionnel : fonction de parsing log
#    is_vr_active() -> bool             — état VR courant (mis en cache)
#    get_source() -> str                — source de détection ("flat", "cmdline:…", etc.)
#    refresh(proc=None, force=False)    — rafraîchit la détection si nécessaire
# =============================================================================

import os
import ctypes
import ctypes.wintypes
import time
import winreg

import psutil

# ─────────────────────────────────────────────────────────────────────────────
#  LISTES DE RÉFÉRENCE
# ─────────────────────────────────────────────────────────────────────────────
VR_RUNTIME_PROCESS_NAMES = frozenset((
    "vrserver.exe",
    "vrmonitor.exe",
    "vrcompositor.exe",
    "vrdashboard.exe",
    "steamvr.exe",
    "openxr-explorer.exe",
    "mixedrealityportal.exe",
    "mixedrealityvrserver.exe",
    "ovrserver_x64.exe",
))

# Arguments de ligne de commande qui indiquent le VR
VR_CMDLINE_HINTS = ("-vr", "-openvr", "-openxr", "-oculus", "/vr")

# Modules DLL chargés dans le processus qui indiquent le VR
VR_MODULE_HINTS = (
    "openvr_api",
    "openxr_loader",
    "libovrrt",
    "oculus",
    "mixedreality",
    "steamxr",
)

# Modules "forts" → indiquent VR de façon certaine (pas besoin d'autres signaux)
VR_STRONG_MODULE_HINTS = ("libovrrt", "oculus", "mixedreality", "steamxr")

# Jeux connus pour charger des DLL VR même en mode écran plat.
# Pour ceux-là, seuls la ligne de commande (et éventuellement un parser de log
# spécifique fourni par l'appelant) sont considérés comme fiables.
STRICT_CMDLINE_ONLY_EXE_NAMES = frozenset((
    "acc.exe",
    "ac2-win64-shipping.exe",
))

# Intervalles de re-détection (secondes)
VR_REFRESH_INTERVAL_FLAT = 2.0
VR_REFRESH_INTERVAL_VR   = 60.0


# ─────────────────────────────────────────────────────────────────────────────
#  ÉTAT INTERNE
# ─────────────────────────────────────────────────────────────────────────────
_vr_active       = False
_vr_source       = "flat"
_vr_last_pid     = None
_vr_last_check   = 0.0
_game_log_parser = None   # callable(proc) -> bool | None — spécifique au jeu


# ─────────────────────────────────────────────────────────────────────────────
#  CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────
def configure(game_log_parser=None) -> None:
    """
    Configure un parser de log optionnel spécifique au jeu.
    game_log_parser(proc) doit retourner True/False ou None si non déterminable.
    Exemple : ACE écrit dans ses logs si la session est VR.
    """
    global _game_log_parser
    _game_log_parser = game_log_parser if callable(game_log_parser) else None


# ─────────────────────────────────────────────────────────────────────────────
#  FONCTIONS UTILITAIRES
# ─────────────────────────────────────────────────────────────────────────────
def _cmdline_lower(proc) -> str:
    try:
        return " ".join(proc.cmdline()).lower()
    except Exception:
        return ""


def _process_name_lower(proc) -> str:
    try:
        return (proc.name() or "").lower()
    except Exception:
        return ""


def _running_vr_process_names() -> set:
    names = set()
    for proc in psutil.process_iter(["name"]):
        try:
            name = (proc.info.get("name") or "").lower()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if name in VR_RUNTIME_PROCESS_NAMES:
            names.add(name)
    return names


def _read_active_openxr_runtime() -> str:
    """Lit le runtime OpenXR actif depuis le registre Windows."""
    candidates = [
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Khronos\OpenXR\1"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Khronos\OpenXR\1"),
    ]
    for hive, path in candidates:
        try:
            with winreg.OpenKey(hive, path) as key:
                value, _ = winreg.QueryValueEx(key, "ActiveRuntime")
                if value:
                    return os.path.basename(str(value)).lower()
        except Exception:
            continue
    return ""


def _list_process_module_names(proc) -> set:
    """Retourne les noms de modules DLL chargés dans le processus."""
    modules = set()
    pid = int(getattr(proc, "pid", 0) or 0)
    if pid <= 0:
        return modules

    TH32CS_SNAPMODULE   = 0x00000008
    TH32CS_SNAPMODULE32 = 0x00000010
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    class MODULEENTRY32(ctypes.Structure):
        _fields_ = [
            ("dwSize",        ctypes.wintypes.DWORD),
            ("th32ModuleID",  ctypes.wintypes.DWORD),
            ("th32ProcessID", ctypes.wintypes.DWORD),
            ("GlblcntUsage",  ctypes.wintypes.DWORD),
            ("ProccntUsage",  ctypes.wintypes.DWORD),
            ("modBaseAddr",   ctypes.POINTER(ctypes.c_byte)),
            ("modBaseSize",   ctypes.wintypes.DWORD),
            ("hModule",       ctypes.wintypes.HMODULE),
            ("szModule",      ctypes.c_wchar * 256),
            ("szExePath",     ctypes.c_wchar * ctypes.wintypes.MAX_PATH),
        ]

    kernel32 = ctypes.windll.kernel32
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
    if snapshot == INVALID_HANDLE_VALUE:
        return modules
    try:
        entry = MODULEENTRY32()
        entry.dwSize = ctypes.sizeof(MODULEENTRY32)
        if kernel32.Module32FirstW(snapshot, ctypes.byref(entry)):
            while True:
                name = (entry.szModule or "").strip().lower()
                if name:
                    modules.add(name)
                if not kernel32.Module32NextW(snapshot, ctypes.byref(entry)):
                    break
    finally:
        kernel32.CloseHandle(snapshot)
    return modules


# ─────────────────────────────────────────────────────────────────────────────
#  LOGIQUE DE DÉTECTION
# ─────────────────────────────────────────────────────────────────────────────
def _detect(proc=None, lightweight: bool = False):
    """
    Retourne (vr_active: bool, source: str).

    Ne se base QUE sur le processus du jeu lui-même pour éviter les faux
    positifs (SteamVR en fond, OpenXR installé mais non utilisé, etc.).

    Ordre de priorité :
      1. Argument -vr / -openvr / -openxr / -oculus dans la cmdline du jeu
      2. Parser de log spécifique au jeu (si configuré)
      3. Modules VR forts chargés dans le processus (libovrrt, oculus,
         mixedreality, steamxr) — ignoré si lightweight
      4. Memory maps du processus contenant un chemin vers un DLL VR fort
         — ignoré si lightweight
    """
    if proc is None:
        return False, "flat"

    proc_name = _process_name_lower(proc)

    # 1. Ligne de commande du jeu
    cmdline = _cmdline_lower(proc)
    for hint in VR_CMDLINE_HINTS:
        if hint in cmdline:
            return True, f"cmdline:{hint}"

    # 2. Parser de log spécifique au jeu
    if _game_log_parser is not None:
        try:
            result = _game_log_parser(proc)
            if result is True:
                return True, "game_log"
            if result is False:
                return False, "flat"
        except Exception:
            pass

    # ACC charge parfois des DLL Oculus/OpenXR même en flat.
    # Pour éviter les faux positifs, on s'arrête ici pour les exécutables
    # connus de ce jeu si aucun signal explicite n'a confirmé le VR.
    if proc_name in STRICT_CMDLINE_ONLY_EXE_NAMES:
        return False, "flat"

    if lightweight:
        return False, "flat"

    # 3. Modules VR forts chargés dans le processus jeu
    try:
        mods = _list_process_module_names(proc)
        for mod in sorted(mods):
            if any(hint in mod for hint in VR_STRONG_MODULE_HINTS):
                return True, f"module:{mod}"
    except Exception:
        pass

    # 4. Memory maps du processus (DLL VR mappés en mémoire)
    try:
        for mapping in proc.memory_maps(grouped=False):
            path = (mapping.path or "").lower()
            if any(hint in path for hint in VR_STRONG_MODULE_HINTS):
                return True, f"module:{os.path.basename(path)}"
    except Exception:
        pass

    return False, "flat"


# ─────────────────────────────────────────────────────────────────────────────
#  API PUBLIQUE
# ─────────────────────────────────────────────────────────────────────────────
def is_vr_active() -> bool:
    """Retourne l'état VR mis en cache (mis à jour par refresh())."""
    return _vr_active


def get_source() -> str:
    """Retourne la source de la dernière détection VR."""
    return _vr_source


def refresh(proc=None, force: bool = False) -> bool:
    """
    Rafraîchit la détection VR si l'intervalle est écoulé ou si force=True.
    Retourne True si l'état VR a changé.
    """
    global _vr_active, _vr_source, _vr_last_pid, _vr_last_check

    pid = getattr(proc, "pid", None)
    now = time.time()
    interval = VR_REFRESH_INTERVAL_VR if _vr_active else VR_REFRESH_INTERVAL_FLAT

    if not force and pid == _vr_last_pid and (now - _vr_last_check) < interval:
        return False

    # En mode VR déjà actif, on fait une vérification allégée (lightweight)
    lightweight = _vr_active and not force
    new_active, new_source = _detect(proc, lightweight=lightweight)

    # En vérification allégée, _detect() saute le scan de modules (coûteux) et
    # retourne False si aucun signal cmdline/log ne confirme le VR.
    # Si c'était le seul moyen de détection initial, cela réinitialise _vr_active
    # à False à chaque cycle de 60 s — ce qui coupe les TTS en VR.
    # Correction : si la détection allégée ne trouve aucun signal positif,
    # conserver l'état et la source actuels (le VR ne se désactive pas en session).
    if lightweight and not new_active:
        new_active = _vr_active
        new_source = _vr_source

    _vr_last_check = now
    changed = (
        force
        or pid != _vr_last_pid
        or new_active != _vr_active
        or new_source != _vr_source
    )
    _vr_last_pid = pid
    _vr_active   = new_active
    _vr_source   = new_source
    return changed
