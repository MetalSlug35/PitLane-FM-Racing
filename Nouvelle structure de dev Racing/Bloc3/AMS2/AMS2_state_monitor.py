# =============================================================================
#  Bloc3 — AMS2_state_monitor.py
#  Surveillance de l'état du jeu Automobilista 2 (AMS2).
#  Utilise la shared memory $pcars2$ via ctypes.
#
#  API publique (interface normalisée Bloc3) :
#    find_process() -> psutil.Process | None
#    get_state(precedent: dict | None) -> dict
# =============================================================================

from __future__ import annotations
import ctypes as C
import ctypes.wintypes as W
import psutil

# ─────────────────────────────────────────────────────────────────────────────
#  CONSTANTES SHARED MEMORY AMS2
# ─────────────────────────────────────────────────────────────────────────────
MAP_NAME               = "$pcars2$"
FILE_MAP_READ          = 0x0004
STRING_LENGTH_MAX      = 64
STORED_PARTICIPANTS_MAX = 64
VEC_MAX                = 3
AMS2_EXES = frozenset(("ams2avx.exe", "ams2.exe", "automobilista2.exe"))

GAME    = {0: "GAME_EXITED", 1: "GAME_FRONT_END", 2: "GAME_INGAME_PLAYING",
           3: "GAME_INGAME_PAUSED", 4: "GAME_INGAME_INMENU_TIME_TICKING",
           5: "GAME_INGAME_RESTARTING", 6: "GAME_INGAME_REPLAY", 7: "GAME_FRONT_END_REPLAY"}
SESSION = {0: "SESSION_INVALID", 1: "SESSION_PRACTICE", 2: "SESSION_TEST",
           3: "SESSION_QUALIFY", 4: "SESSION_FORMATION_LAP", 5: "SESSION_RACE",
           6: "SESSION_TIME_ATTACK"}
RACE    = {0: "RACESTATE_INVALID", 1: "RACESTATE_NOT_STARTED", 2: "RACESTATE_RACING",
           3: "RACESTATE_FINISHED", 4: "RACESTATE_DISQUALIFIED", 5: "RACESTATE_RETIRED",
           6: "RACESTATE_DNF"}
PIT     = {0: "PIT_MODE_NONE", 1: "PIT_MODE_DRIVING_INTO_PITS", 2: "PIT_MODE_IN_PIT",
           3: "PIT_MODE_DRIVING_OUT_OF_PITS", 4: "PIT_MODE_IN_GARAGE",
           5: "PIT_MODE_DRIVING_OUT_OF_GARAGE"}
FLAG    = {0: "NONE", 1: "GREEN", 2: "BLUE", 3: "WHITE_SLOW", 4: "WHITE_FINAL",
           5: "RED", 6: "YELLOW", 7: "DOUBLE_YELLOW", 8: "BLACK_WHITE",
           9: "BLACK_ORANGE", 10: "BLACK", 11: "CHEQUERED"}
CAR_SPEED_LIMITER = 1 << 3

# ─────────────────────────────────────────────────────────────────────────────
#  STRUCTURES CTYPES
# ─────────────────────────────────────────────────────────────────────────────
class ParticipantInfo(C.Structure):
    _fields_ = [
        ("mIsActive",          C.c_bool),
        ("mName",              C.c_char * STRING_LENGTH_MAX),
        ("mWorldPosition",     C.c_float * VEC_MAX),
        ("mCurrentLapDistance",C.c_float),
        ("mRacePosition",      C.c_uint),
        ("mLapsCompleted",     C.c_uint),
        ("mCurrentLap",        C.c_uint),
        ("mCurrentSector",     C.c_int),
    ]


class SharedMemoryPrefix(C.Structure):
    _fields_ = [
        ("mVersion",            C.c_uint),
        ("mBuildVersionNumber", C.c_uint),
        ("mGameState",          C.c_uint),
        ("mSessionState",       C.c_uint),
        ("mRaceState",          C.c_uint),
        ("mViewedParticipantIndex", C.c_int),
        ("mNumParticipants",    C.c_int),
        ("mParticipantInfo",    ParticipantInfo * STORED_PARTICIPANTS_MAX),
        ("mUnfilteredThrottle", C.c_float),
        ("mUnfilteredBrake",    C.c_float),
        ("mUnfilteredSteering", C.c_float),
        ("mUnfilteredClutch",   C.c_float),
        ("mCarName",            C.c_char * STRING_LENGTH_MAX),
        ("mCarClassName",       C.c_char * STRING_LENGTH_MAX),
        ("mLapsInEvent",        C.c_uint),
        ("mTrackLocation",      C.c_char * STRING_LENGTH_MAX),
        ("mTrackVariation",     C.c_char * STRING_LENGTH_MAX),
        ("mTrackLength",        C.c_float),
        ("mNumSectors",         C.c_int),
        ("mLapInvalidated",     C.c_bool),
        ("mBestLapTime",        C.c_float),
        ("mLastLapTime",        C.c_float),
        ("mCurrentTime",        C.c_float),
        ("mSplitTimeAhead",     C.c_float),
        ("mSplitTimeBehind",    C.c_float),
        ("mSplitTime",          C.c_float),
        ("mEventTimeRemaining", C.c_float),
        ("mPersonalFastestLapTime", C.c_float),
        ("mWorldFastestLapTime",    C.c_float),
        ("mCurrentSector1Time", C.c_float),
        ("mCurrentSector2Time", C.c_float),
        ("mCurrentSector3Time", C.c_float),
        ("mFastestSector1Time", C.c_float),
        ("mFastestSector2Time", C.c_float),
        ("mFastestSector3Time", C.c_float),
        ("mPersonalFastestSector1Time", C.c_float),
        ("mPersonalFastestSector2Time", C.c_float),
        ("mPersonalFastestSector3Time", C.c_float),
        ("mWorldFastestSector1Time", C.c_float),
        ("mWorldFastestSector2Time", C.c_float),
        ("mWorldFastestSector3Time", C.c_float),
        ("mHighestFlagColour",  C.c_uint),
        ("mHighestFlagReason",  C.c_uint),
        ("mPitMode",            C.c_uint),
        ("mPitSchedule",        C.c_uint),
        ("mCarFlags",           C.c_uint),
        ("mOilTempCelsius",     C.c_float),
        ("mOilPressureKPa",     C.c_float),
        ("mWaterTempCelsius",   C.c_float),
        ("mWaterPressureKPa",   C.c_float),
        ("mFuelPressureKPa",    C.c_float),
        ("mFuelLevel",          C.c_float),
        ("mFuelCapacity",       C.c_float),
        ("mSpeed",              C.c_float),
        ("mRpm",                C.c_float),
        ("mMaxRPM",             C.c_float),
        ("mBrake",              C.c_float),
        ("mThrottle",           C.c_float),
        ("mClutch",             C.c_float),
        ("mSteering",           C.c_float),
        ("mGear",               C.c_int),
        ("mNumGears",           C.c_int),
        ("mOdometerKM",         C.c_float),
        ("mAntiLockActive",     C.c_bool),
        ("mLastOpponentCollisionIndex",     C.c_int),
        ("mLastOpponentCollisionMagnitude", C.c_float),
        ("mBoostActive",        C.c_bool),
        ("mBoostAmount",        C.c_float),
    ]


# ─────────────────────────────────────────────────────────────────────────────
#  LECTURE SHARED MEMORY
# ─────────────────────────────────────────────────────────────────────────────
_k32 = C.WinDLL("kernel32", use_last_error=True)

# argtypes/restype explicites pour éviter la troncature du pointeur 64-bit
_k32.OpenFileMappingW.argtypes = [W.DWORD, W.BOOL, W.LPCWSTR]
_k32.OpenFileMappingW.restype  = W.HANDLE
_k32.MapViewOfFile.argtypes    = [W.HANDLE, W.DWORD, W.DWORD, W.DWORD, C.c_size_t]
_k32.MapViewOfFile.restype     = W.LPVOID
_k32.UnmapViewOfFile.argtypes  = [W.LPCVOID]
_k32.UnmapViewOfFile.restype   = W.BOOL
_k32.CloseHandle.argtypes      = [W.HANDLE]
_k32.CloseHandle.restype       = W.BOOL


def _read_shared_memory() -> SharedMemoryPrefix | None:
    handle = _k32.OpenFileMappingW(FILE_MAP_READ, False, MAP_NAME)
    if not handle:
        return None
    size = C.sizeof(SharedMemoryPrefix)
    ptr  = _k32.MapViewOfFile(handle, FILE_MAP_READ, 0, 0, size)
    _k32.CloseHandle(handle)
    if not ptr:
        return None
    try:
        raw = C.string_at(ptr, size)
    finally:
        _k32.UnmapViewOfFile(ptr)
    data = SharedMemoryPrefix()
    C.memmove(C.byref(data), raw, size)
    return data


# ─────────────────────────────────────────────────────────────────────────────
#  CLASSEMENT D'ÉTAT
# ─────────────────────────────────────────────────────────────────────────────
def _classify(proc, data: SharedMemoryPrefix | None) -> dict:
    snap = {
        "stateId": "unknown",
        "stateLabel": "Inconnu",
        "speedKph": 0.0,
        "currentTimeMs": 0,
        "rawNormalizedCarPosition": 0.0,
        "sessionState": "",
        "pitMode": "PIT_NONE",
        "flagColour": "",
        "signals": [],
        "events": [],
        "raceStartInferred": False,
        "greenLightInferred": False,
        "gameState": "",
        "raceState": "",
    }

    if proc is None:
        snap["stateId"], snap["stateLabel"] = "game_closed", "Jeu fermé"
        return snap

    if data is None:
        snap["stateId"], snap["stateLabel"] = "loading", "Chargement"
        return snap

    gs   = int(data.mGameState)
    ss   = int(data.mSessionState)
    rs   = int(data.mRaceState)
    pit  = int(data.mPitMode)
    flag = int(data.mHighestFlagColour)

    snap["gameState"]    = GAME.get(gs, str(gs))
    snap["sessionState"] = SESSION.get(ss, str(ss))
    snap["raceState"]    = RACE.get(rs, str(rs))
    snap["pitMode"]      = PIT.get(pit, str(pit))
    snap["flagColour"]   = FLAG.get(flag, str(flag))
    snap["speedKph"]     = float(data.mSpeed) * 3.6  # m/s → km/h

    # Signals
    sigs = []
    if flag == 1:   sigs.append("green_flag")
    if flag in (6, 7): sigs.append("yellow_flag")
    if flag == 5:   sigs.append("red_flag")
    if flag == 11:  sigs.append("chequered_flag")
    if data.mCarFlags & CAR_SPEED_LIMITER:
        sigs.append("pit_limiter")
    snap["signals"] = sorted(set(sigs))

    # Pit mode mapping
    if pit in (1, 3):  # DRIVING_INTO / DRIVING_OUT
        snap["pitMode"] = "PIT_LANE"
    elif pit in (2, 4, 5):  # IN_PIT / IN_GARAGE / DRIVING_OUT_OF_GARAGE
        snap["pitMode"] = "PIT_STOP"

    # Classification
    if gs == 0:  # GAME_EXITED
        snap["stateId"], snap["stateLabel"] = "game_closed", "Jeu fermé"
    elif gs == 1:  # FRONT_END
        snap["stateId"], snap["stateLabel"] = "menus", "Menus"
    elif gs == 7:  # FRONT_END_REPLAY
        snap["stateId"], snap["stateLabel"] = "menus", "Menus"
    elif gs == 6:  # REPLAY
        snap["stateId"], snap["stateLabel"] = "replay", "Replay"
    elif gs == 3:  # PAUSED
        snap["stateId"], snap["stateLabel"] = "paused", "Pause"
    elif gs == 4:  # INMENU_TIME_TICKING
        snap["stateId"], snap["stateLabel"] = "setup_menu", "Menu setup"
    elif gs == 5:  # RESTARTING
        snap["stateId"], snap["stateLabel"] = "loading", "Redémarrage"
    elif gs == 2:  # INGAME_PLAYING
        if pit in (2, 4):
            snap["stateId"], snap["stateLabel"] = "pit_stop", "Stand"
        elif pit in (1, 3, 5):
            snap["stateId"], snap["stateLabel"] = "pit_lane", "Voie des stands"
        elif ss == 5:  # SESSION_RACE
            if rs == 1:  # NOT_STARTED
                snap["stateId"], snap["stateLabel"] = "pre_race", "Grille / avant départ"
            else:
                snap["stateId"], snap["stateLabel"] = "race", "En course"
                if rs == 2:
                    snap["raceStartInferred"] = True
        elif ss in (1, 2):  # PRACTICE / TEST
            snap["stateId"], snap["stateLabel"] = "practice", "Essais"
        elif ss == 3:  # QUALIFY
            snap["stateId"], snap["stateLabel"] = "qualifying", "Qualifications"
        elif ss == 4:  # FORMATION_LAP
            snap["stateId"], snap["stateLabel"] = "pre_race", "Tour de formation"
        elif ss == 6:  # TIME_ATTACK
            snap["stateId"], snap["stateLabel"] = "time_attack", "Time attack"
        else:
            snap["stateId"], snap["stateLabel"] = "on_track", "En piste"

    return snap


def _infer_events(snap: dict, precedent: dict | None) -> dict:
    if precedent is None:
        return snap
    events = []
    prev_id = precedent.get("stateId", "")
    cur_id  = snap.get("stateId", "")
    sigs    = set(snap.get("signals", []))
    prev_s  = set(precedent.get("signals", []))

    if prev_id == "paused" and cur_id in {"setup_menu", "pit_lane", "pit_stop"}:
        events.append("garage_return_pause_menu")
    if prev_id == "setup_menu" and cur_id in {"pit_lane", "pit_stop"}:
        events.append("garage_return_direct")
    if "green_flag" in sigs and "green_flag" not in prev_s and cur_id == "race":
        events.append("race_start")
        snap["greenLightInferred"] = True

    snap["events"] = sorted(set(events))
    return snap


# ─────────────────────────────────────────────────────────────────────────────
#  API PUBLIQUE
# ─────────────────────────────────────────────────────────────────────────────
def find_process():
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if (proc.info.get("name") or "").lower() in AMS2_EXES:
                return proc
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return None


def get_state(precedent: dict | None = None) -> dict:
    proc = find_process()
    data = _read_shared_memory() if proc is not None else None
    snap = _classify(proc, data)
    return _infer_events(snap, precedent)
