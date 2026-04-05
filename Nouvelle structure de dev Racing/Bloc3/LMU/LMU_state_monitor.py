# =============================================================================
#  Bloc3 — LMU_state_monitor.py
#  Surveillance de l'état du jeu Le Mans Ultimate (LMU).
#  LMU est basé sur rFactor 2 et expose sa propre shared memory "LMU_Data"
#  (format Madness Engine / rFactor 2) — incompatible avec pyaccsharedmemory.
#
#  API publique (interface normalisée Bloc3) :
#    find_process() -> psutil.Process | None
#    get_state(precedent: dict | None) -> dict
# =============================================================================

from __future__ import annotations

import ctypes
import ctypes.wintypes
import struct as _struct
import time

import psutil

# ─────────────────────────────────────────────────────────────────────────────
#  CONSTANTES
# ─────────────────────────────────────────────────────────────────────────────
LMU_EXE_NAMES = frozenset((
    "lemansultimate.exe",
    "le mans ultimate.exe",
    "lemanultimate.exe",
    "lmu.exe",
))

# ─────────────────────────────────────────────────────────────────────────────
#  SHARED MEMORY LMU_Data (rFactor 2 / Madness Engine)
#
#  Layout SharedMemoryGeneric :
#    events[16] uint32[16]          @   0  (64 o)
#    gameVersion long               @  64
#    FFBTorque float                @  68
#    ApplicationStateV01            @  72
#      HWND mAppWindow ptr(8)       @  72
#      ulong mWidth                 @  80
#      ulong mHeight                @  84
#      ulong mRefreshRate           @  88
#      ulong mWindowed              @  92
#      uchar mOptionsLocation       @  96
#      char  mOptionsPage[31]       @  97
#      uchar mExpansion[204]        @ 128
#    end ApplicationStateV01        @ 332
#    SharedMemoryPathData (5*260)   @ 332  → 1300 o
#
#  Layout SharedMemoryScoringData.ScoringInfoV01 @ 1632 :
#    char  mTrackName[64]           @ 1632
#    long  mSession                 @ 1696
#    double mCurrentET              @ 1700
#    double mEndET                  @ 1708
#    long  mMaxLaps                 @ 1716
#    double mLapDist                @ 1720
#    ptr   mResultsStream           @ 1728  (8 o 64-bit)
#    long  mNumVehicles             @ 1736
#    uchar mGamePhase               @ 1740
#    schar mYellowFlagState         @ 1741
#    schar mSectorFlag[3]           @ 1742
#    uchar mStartLight              @ 1745
#    uchar mNumRedLights            @ 1746
#    bool  mInRealtime              @ 1747
#
#  Tableau VehicleScoringInfoV01[104] @ 1632+556 = 2188 :
#    sizeof(VehicleScoringInfoV01) = 584 (pack=4)
#    VEH_OFF_FINISH   = 103   (mFinishStatus : 0=none 1=fini 2=dnf 3=dq)
#    VEH_OFF_ISPLAYER = 196   (mIsPlayer bool)
# ─────────────────────────────────────────────────────────────────────────────
SM_NAME      = "LMU_Data"
SM_READ_SIZE = 131072        # 128 Ko

FILE_MAP_READ = 0x0004

SC               = 1632
OFF_TRACK_NAME   = SC + 0    # char[64]
OFF_SESSION      = SC + 64   # long (int32)
OFF_NUM_VEH      = SC + 104  # long
OFF_GAME_PHASE   = SC + 108  # uchar
OFF_YEL_STATE    = SC + 109  # schar
OFF_IN_REALTIME  = SC + 115  # bool

OFF_VEH_ARRAY    = SC + 556  # début tableau VehicleScoringInfoV01[104]
VEH_SIZE         = 584
VEH_OFF_FINISH   = 103       # mFinishStatus
VEH_OFF_ISPLAYER = 196       # mIsPlayer

# Sessions LMU (rFactor 2)
# 1-4  : Essais libres / Free practice
# 5-8  : Qualifications
# 9    : Warm-up
# 10-13: Course (Race)
SESSION_PRACTICE   = range(1, 5)
SESSION_QUALIFY    = range(5, 9)
SESSION_WARMUP     = (9,)
SESSION_RACE       = range(10, 14)

# Phases de course (mGamePhase)
# 0=before session / 1=reconnaissance laps / 2=reconnaissance laps complete
# 3=grid walk-through / 4=formation lap / 5=green flag (course active)
# 6=full course yellow / 7=session stopped (chequered waved)
# 8=session over (leader crossed) / 9=session finished
PHASE_FORMATION   = (3, 4)   # formation / grid
PHASE_GREEN       = 5        # drapeau vert
PHASE_FINISH      = (7, 8, 9)

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.OpenFileMappingA.restype  = ctypes.wintypes.HANDLE
_k32.OpenFileMappingA.argtypes = [ctypes.wintypes.DWORD,
                                   ctypes.wintypes.BOOL,
                                   ctypes.c_char_p]
_k32.MapViewOfFile.restype     = ctypes.c_void_p
_k32.MapViewOfFile.argtypes    = [ctypes.wintypes.HANDLE,
                                   ctypes.wintypes.DWORD,
                                   ctypes.wintypes.DWORD,
                                   ctypes.wintypes.DWORD,
                                   ctypes.c_size_t]
_k32.UnmapViewOfFile.argtypes  = [ctypes.c_void_p]
_k32.CloseHandle.argtypes      = [ctypes.wintypes.HANDLE]


def _read_lmu_sm() -> bytes | None:
    h = _k32.OpenFileMappingA(FILE_MAP_READ, False, SM_NAME.encode("ascii"))
    if not h:
        return None
    ptr = _k32.MapViewOfFile(h, FILE_MAP_READ, 0, 0, SM_READ_SIZE)
    if not ptr:
        _k32.CloseHandle(h)
        return None
    try:
        buf = (ctypes.c_ubyte * SM_READ_SIZE).from_address(ptr)
        return bytes(buf)
    finally:
        _k32.UnmapViewOfFile(ptr)
        _k32.CloseHandle(h)


def _i32(b: bytes, o: int) -> int:
    return _struct.unpack_from("<i", b, o)[0]

def _u8(b: bytes, o: int) -> int:
    return b[o]

def _i8(b: bytes, o: int) -> int:
    return _struct.unpack_from("<b", b, o)[0]

def _str64(b: bytes, o: int) -> str:
    return b[o:o + 64].split(b"\x00")[0].decode("ascii", "replace").strip()


def _lire_sm() -> dict | None:
    """
    Lit la Shared Memory LMU_Data.
    Retourne un dict ou None si LMU n'a pas encore exposé la SM.
    """
    raw = _read_lmu_sm()
    if raw is None or len(raw) < OFF_IN_REALTIME + 4:
        return None

    num_v = _i32(raw, OFF_NUM_VEH)

    # Cherche le véhicule du joueur et son statut de fin
    joueur_fini = False
    for i in range(min(num_v, 104)):
        base = OFF_VEH_ARRAY + i * VEH_SIZE
        if base + VEH_SIZE > len(raw):
            break
        if _u8(raw, base + VEH_OFF_ISPLAYER):
            joueur_fini = (_i8(raw, base + VEH_OFF_FINISH) == 1)
            break

    return {
        "track":        _str64(raw, OFF_TRACK_NAME),
        "session":      _i32(raw, OFF_SESSION),
        "num_vehicles": num_v,
        "game_phase":   _u8(raw, OFF_GAME_PHASE),
        "yel_state":    _i8(raw, OFF_YEL_STATE),
        "in_realtime":  bool(_u8(raw, OFF_IN_REALTIME)),
        "joueur_fini":  joueur_fini,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  CLASSEMENT D'ÉTAT
# ─────────────────────────────────────────────────────────────────────────────
def _classify(proc, sm: dict | None) -> dict:
    snap = {
        "stateId":                  "unknown",
        "stateLabel":               "Inconnu",
        "gameState":                "",
        "sessionState":             "",
        "raceState":                "",
        "pitMode":                  "PIT_NONE",
        "flagColour":               "",
        "speedKph":                 0.0,
        "currentTimeMs":            0,
        "rawNormalizedCarPosition": 0.0,
        "signals":                  [],
        "events":                   [],
        "raceStartInferred":        False,
        "greenLightInferred":       False,
    }

    if proc is None:
        snap["stateId"]    = "game_closed"
        snap["stateLabel"] = "Jeu fermé"
        snap["gameState"]  = "CLOSED"
        return snap

    if sm is None:
        snap["stateId"]    = "loading"
        snap["stateLabel"] = "Chargement"
        snap["gameState"]  = "LOADING"
        return snap

    in_rt   = sm["in_realtime"]
    session = sm["session"]
    phase   = sm["game_phase"]
    num_v   = sm["num_vehicles"]
    yel     = sm["yel_state"]
    joueur_fini = sm["joueur_fini"]

    snap["gameState"]  = "REALTIME" if in_rt else "MENU"
    snap["sessionState"] = str(session)

    # Signals
    sigs = []
    under_yel = (0 < yel <= 6) or phase == 6
    if phase == PHASE_GREEN and not under_yel:
        sigs.append("green_flag")
    if under_yel:
        sigs.append("yellow_flag")
    if phase in PHASE_FINISH:
        sigs.append("chequered_flag")
    snap["signals"] = sorted(set(sigs))

    # ── Menus principaux (session=0, pas en piste, pas de véhicules) ──────────
    if not in_rt and session == 0 and num_v == 0:
        snap["stateId"]    = "menus"
        snap["stateLabel"] = "Menus"
        return snap

    # ── Garage / Monitor (session active mais pas au volant) ──────────────────
    if not in_rt:
        snap["stateId"]    = "setup_menu"
        snap["stateLabel"] = "Garage / Monitor"
        return snap

    # ── En piste (in_realtime=True) ───────────────────────────────────────────

    # Essais libres
    if session in SESSION_PRACTICE:
        snap["stateId"]    = "practice"
        snap["stateLabel"] = "Essais libres"
        snap["sessionState"] = "PRACTICE"
        return snap

    # Qualifications
    if session in SESSION_QUALIFY:
        snap["stateId"]    = "qualifying"
        snap["stateLabel"] = "Qualifications"
        snap["sessionState"] = "QUALIFY"
        return snap

    # Warm-up
    if session in SESSION_WARMUP:
        snap["stateId"]    = "practice"
        snap["stateLabel"] = "Warm-up"
        snap["sessionState"] = "WARMUP"
        return snap

    # Course
    if session in SESSION_RACE:
        snap["sessionState"] = "RACE"
        snap["raceState"]    = f"phase_{phase}"

        if phase == PHASE_GREEN:
            # Drapeau vert : musique !
            if under_yel:
                # Safety car → pause musicale
                snap["stateId"]    = "pre_race"
                snap["stateLabel"] = "Voiture de sécurité"
            else:
                snap["stateId"]    = "race"
                snap["stateLabel"] = "En course"
            return snap

        if phase in PHASE_FINISH:
            # Fin de course : continuer la musique si le joueur n'a pas encore
            # passé la ligne (reproduit le comportement du monolithique)
            if joueur_fini:
                snap["stateId"]    = "pre_race"
                snap["stateLabel"] = "Course terminée"
            else:
                snap["stateId"]    = "race"
                snap["stateLabel"] = "En course (fin)"
            return snap

        if phase in PHASE_FORMATION:
            snap["stateId"]    = "pre_race"
            snap["stateLabel"] = "Tour de formation"
            return snap

        # Phase 0-2 (avant session) ou phase 6 (FCY global) → stop
        snap["stateId"]    = "pre_race"
        snap["stateLabel"] = "Avant départ"
        return snap

    # Session non classifiée mais in_realtime
    snap["stateId"]    = "on_track"
    snap["stateLabel"] = "En piste"
    return snap


# ─────────────────────────────────────────────────────────────────────────────
#  INFÉRENCE D'ÉVÉNEMENTS
# ─────────────────────────────────────────────────────────────────────────────
def _infer_events(snap: dict, precedent: dict | None) -> dict:
    if precedent is None:
        return snap

    events   = []
    prev_id  = precedent.get("stateId", "")
    cur_id   = snap.get("stateId", "")
    sigs     = set(snap.get("signals", []))
    prev_sig = set(precedent.get("signals", []))

    if prev_id != cur_id:
        events.append("state_changed")

    if prev_id == "setup_menu" and cur_id in {"menus"}:
        events.append("garage_return_direct")

    # Drapeau vert apparu pendant la course → race_start
    if "green_flag" in sigs and "green_flag" not in prev_sig and cur_id == "race":
        events.append("race_start")
        snap["raceStartInferred"]  = True
        snap["greenLightInferred"] = True

    snap["events"] = sorted(set(events))
    return snap


# ─────────────────────────────────────────────────────────────────────────────
#  API PUBLIQUE
# ─────────────────────────────────────────────────────────────────────────────
def find_process():
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if (proc.info.get("name") or "").lower() in LMU_EXE_NAMES:
                return proc
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return None


def get_state(precedent: dict | None = None) -> dict:
    proc = find_process()
    sm   = _lire_sm() if proc is not None else None
    snap = _classify(proc, sm)
    return _infer_events(snap, precedent)
