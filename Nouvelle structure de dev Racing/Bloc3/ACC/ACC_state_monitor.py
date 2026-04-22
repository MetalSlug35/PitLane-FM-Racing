# =============================================================================
#  Bloc3 — ACC_state_monitor.py
#  Surveillance de l'état du jeu Assetto Corsa Competizione (ACC).
#  Utilise la shared memory via pyaccsharedmemory.
#
#  API publique (interface normalisée Bloc3) :
#    find_process() -> psutil.Process | None
#    get_state(precedent: dict | None) -> dict
#
#  Format de sortie normalisé (compatible Bloc4 coordinateur) :
#    {
#      "stateId"       : str   — identifiant normalisé (voir tableau)
#      "stateLabel"    : str   — libellé lisible
#      "speedKph"      : float
#      "currentTimeMs" : int
#      "rawNormalizedCarPosition" : float
#      "sessionState"  : str   — ACC_RACE / ACC_PRACTICE / etc.
#      "pitMode"       : str
#      "flagColour"    : str
#      "signals"       : list[str]
#      "events"        : list[str]
#      "raceStartInferred" : bool
#      "greenLightInferred": bool
#    }
# =============================================================================

from __future__ import annotations
import atexit
import time
import psutil

from pyaccsharedmemory import (
    ACC_FLAG_TYPE,
    ACC_RAIN_INTENSITY,
    ACC_SESSION_TYPE,
    ACC_STATUS,
    accSharedMemory,
    read_graphics_map,
    read_physic_map,
    read_static_map,
)

ACC_EXE_NAMES = frozenset(("acc.exe", "ac2-win64-shipping.exe"))
MOTION_GATED_STATES = frozenset((
    "qualifying",
    "practice",
    "hotlap",
    "hotstint",
    "time_attack",
    "pit_lane",
    "pit_stop",
    "on_track",
))
MOTION_GATE_BLOCK_SECONDS = 2.0
MOTION_GATE_SPEED_KPH = 5.0


# ─────────────────────────────────────────────────────────────────────────────
#  SHARED MEMORY
# ─────────────────────────────────────────────────────────────────────────────
class _SharedMemSource:
    def __init__(self):
        self._reader = None

    def _connect(self) -> bool:
        if self._reader is not None:
            return True
        try:
            self._reader = accSharedMemory()
            return True
        except Exception:
            self._reader = None
            return False

    def read(self) -> tuple[dict | None, str]:
        if not self._connect():
            return None, "mapping_unavailable"
        try:
            physics  = read_physic_map(self._reader.physicSM)
            graphics = read_graphics_map(self._reader.graphicSM)
            statics  = read_static_map(self._reader.staticSM)
            return {"physics": physics, "graphics": graphics, "static": statics}, ""
        except Exception as exc:
            self._close_reader()
            return None, f"read_failed:{exc}"

    def _close_reader(self):
        if self._reader is None:
            return
        try:
            self._reader.close()
        except Exception:
            pass
        self._reader = None

    close = _close_reader


_SRC = _SharedMemSource()
atexit.register(_SRC.close)

_motion_gate_active = False
_motion_gate_block_until = 0.0
_motion_gate_session_key = ""
_motion_gate_last_time_ms = 0
_motion_gate_last_time_left = 0.0


def _reset_motion_gate() -> None:
    global _motion_gate_active, _motion_gate_block_until, _motion_gate_session_key
    global _motion_gate_last_time_ms, _motion_gate_last_time_left
    _motion_gate_active = False
    _motion_gate_block_until = 0.0
    _motion_gate_session_key = ""
    _motion_gate_last_time_ms = 0
    _motion_gate_last_time_left = 0.0


def _safe_enum(v) -> str:
    return getattr(v, "name", str(v))


# ─────────────────────────────────────────────────────────────────────────────
#  CLASSEMENT D'ÉTAT
# ─────────────────────────────────────────────────────────────────────────────
def _classify(proc, shm: dict | None, error: str) -> dict:
    snap = {
        "stateId": "unknown",
        "stateLabel": "Inconnu",
        "speedKph": 0.0,
        "currentTimeMs": 0,
        "rawNormalizedCarPosition": 0.0,
        "sessionState": "",
        "pitMode": "",
        "flagColour": "",
        "signals": [],
        "events": [],
        "raceStartInferred": False,
        "greenLightInferred": False,
        # champs internes bruts
        "gameState": "",
        "raceState": "",
    }

    if proc is None:
        snap["stateId"] = "game_closed"
        snap["stateLabel"] = "Jeu fermé"
        return snap

    if shm is None:
        snap["stateId"] = "loading"
        snap["stateLabel"] = "Chargement"
        return snap

    ph = shm["physics"]
    gr = shm["graphics"]

    snap["gameState"]    = _safe_enum(gr.status)
    snap["sessionState"] = _safe_enum(gr.session_type)
    snap["speedKph"]     = float(getattr(ph, "speed_kmh", 0.0) or 0.0)
    snap["currentTimeMs"] = int(gr.current_time)
    snap["sessionTimeLeft"] = float(getattr(gr, "session_time_left", 0.0) or 0.0)
    snap["rawNormalizedCarPosition"] = float(gr.normalized_car_position)
    snap["flagColour"]   = _safe_enum(gr.flag)
    snap["_rawTrack"] = str(getattr(shm["static"], "track", "") or "")
    snap["_rawCarModel"] = str(getattr(shm["static"], "car_model", "") or "")
    snap["raceState"]    = ""

    if gr.is_in_pit_lane:
        snap["pitMode"] = "PIT_LANE"
    elif gr.is_in_pit:
        snap["pitMode"] = "PIT_STOP"
    else:
        snap["pitMode"] = "PIT_NONE"

    # Signals
    sigs = []
    if gr.flag == ACC_FLAG_TYPE.ACC_GREEN_FLAG or gr.global_green:
        sigs.append("green_flag")
    if (gr.flag == ACC_FLAG_TYPE.ACC_YELLOW_FLAG or gr.global_yellow
            or gr.global_yellow_s1 or gr.global_yellow_s2 or gr.global_yellow_s3):
        sigs.append("yellow_flag")
    if gr.flag == ACC_FLAG_TYPE.ACC_WHITE_FLAG or gr.global_white:
        sigs.append("white_flag")
    if gr.global_red:
        sigs.append("red_flag")
    if gr.flag == ACC_FLAG_TYPE.ACC_CHECKERED_FLAG or gr.global_chequered:
        sigs.append("chequered_flag")
    if ph.pit_limiter_on:
        sigs.append("pit_limiter")
    if gr.rain_tyres:
        sigs.append("rain_tyres")
    if gr.rain_intensity != ACC_RAIN_INTENSITY.ACC_NO_RAIN:
        sigs.append("rain")
    if gr.missing_mandatory_pits > 0:
        sigs.append("mandatory_pit_pending")
    snap["signals"] = sorted(set(sigs))

    # Classification
    status = gr.status
    stype  = gr.session_type
    if status == ACC_STATUS.ACC_OFF:
        snap["stateId"], snap["stateLabel"] = "menus", "Menus"
    elif status == ACC_STATUS.ACC_REPLAY:
        snap["stateId"], snap["stateLabel"] = "replay", "Replay"
    elif status == ACC_STATUS.ACC_PAUSE:
        snap["stateId"], snap["stateLabel"] = "paused", "Pause"
    elif gr.is_setup_menu_visible:
        snap["stateId"], snap["stateLabel"] = "setup_menu", "Menu setup / garage"
    elif gr.is_in_pit_lane:
        snap["stateId"], snap["stateLabel"] = "pit_lane", "Voie des stands"
    elif gr.is_in_pit:
        snap["stateId"], snap["stateLabel"] = "pit_stop", "Stand"
    elif status == ACC_STATUS.ACC_LIVE and stype == ACC_SESSION_TYPE.ACC_RACE and gr.global_red and not gr.global_green:
        snap["stateId"], snap["stateLabel"] = "pre_race", "Grille / avant départ"
    elif status == ACC_STATUS.ACC_LIVE and stype == ACC_SESSION_TYPE.ACC_RACE:
        snap["stateId"], snap["stateLabel"] = "race", "En course"
    elif status == ACC_STATUS.ACC_LIVE and stype == ACC_SESSION_TYPE.ACC_QUALIFY:
        snap["stateId"], snap["stateLabel"] = "qualifying", "Qualifications"
    elif status == ACC_STATUS.ACC_LIVE and stype == ACC_SESSION_TYPE.ACC_PRACTICE:
        snap["stateId"], snap["stateLabel"] = "practice", "Essais"
    elif status == ACC_STATUS.ACC_LIVE and stype == ACC_SESSION_TYPE.ACC_HOTLAP:
        snap["stateId"], snap["stateLabel"] = "hotlap", "Hotlap"
    elif status == ACC_STATUS.ACC_LIVE and stype == ACC_SESSION_TYPE.ACC_HOTSTINT:
        snap["stateId"], snap["stateLabel"] = "hotstint", "Hotstint"
    elif status == ACC_STATUS.ACC_LIVE and stype == ACC_SESSION_TYPE.ACC_TIME_ATTACK:
        snap["stateId"], snap["stateLabel"] = "time_attack", "Time attack"
    elif status == ACC_STATUS.ACC_LIVE:
        snap["stateId"], snap["stateLabel"] = "on_track", "En piste"

    return snap


def _infer_events(snap: dict, precedent: dict | None) -> dict:
    """Ajoute les événements dérivés (garage_return, race_start…)."""
    if precedent is None:
        return snap

    events = list(snap.get("events", []))
    prev_id  = precedent.get("stateId", "")
    cur_id   = snap.get("stateId", "")
    sigs     = set(snap.get("signals", []))
    prev_sig = set(precedent.get("signals", []))

    # Retour garage depuis menu pause
    if prev_id == "paused" and cur_id in {"setup_menu", "pit_lane", "pit_stop"}:
        events.append("garage_return_pause_menu")
    # Retour garage direct depuis course (setup_menu s'intercale)
    if prev_id == "setup_menu" and cur_id in {"pit_lane", "pit_stop", "menus"}:
        events.append("garage_return_direct")
    # Départ course (feu vert inféré depuis l'apparition du green_flag)
    if "green_flag" in sigs and "green_flag" not in prev_sig and cur_id == "race":
        events.append("race_start")
        snap["greenLightInferred"] = True

    snap["events"] = sorted(set(events))
    return snap


# ─────────────────────────────────────────────────────────────────────────────
#  API PUBLIQUE
# ─────────────────────────────────────────────────────────────────────────────
def _apply_motion_gate(snap: dict, precedent: dict | None) -> dict:
    """Bloque les modes hors course jusqu'a 2 s + premier vrai mouvement."""
    global _motion_gate_active, _motion_gate_block_until, _motion_gate_session_key
    global _motion_gate_last_time_ms, _motion_gate_last_time_left

    raw_state = snap.get("stateId", "unknown")
    snap["_rawStateId"] = raw_state

    if raw_state in {"game_closed", "loading", "menus", "setup_menu", "pre_race", "race", "replay", "unknown"}:
        _reset_motion_gate()
        return snap

    if raw_state == "paused":
        return snap

    if raw_state in {"pit_lane", "pit_stop"} and snap.get("sessionState") == "ACC_RACE":
        _reset_motion_gate()
        return snap

    if raw_state not in MOTION_GATED_STATES:
        _reset_motion_gate()
        return snap

    session_key = "|".join((
        str(snap.get("sessionState", "") or ""),
        str(snap.get("_rawTrack", "") or ""),
        str(snap.get("_rawCarModel", "") or ""),
    ))
    current_time_ms = int(snap.get("currentTimeMs", 0) or 0)
    session_time_left = float(snap.get("sessionTimeLeft", 0.0) or 0.0)
    previous_state = str(precedent.get("stateId", "") or "") if precedent else ""

    session_changed = bool(_motion_gate_session_key and session_key != _motion_gate_session_key)
    timer_rollback = (
        _motion_gate_last_time_ms > 5000
        and current_time_ms >= 0
        and current_time_ms + 3000 < _motion_gate_last_time_ms
    )
    timer_restarted_from_stop = (
        previous_state in {"menus", "loading", "setup_menu", "pre_race", "paused"}
        and current_time_ms <= 3000
        and _motion_gate_last_time_ms > 8000
    )
    time_left_jump = (
        _motion_gate_last_time_left > 0.0
        and session_time_left > 0.0
        and session_time_left > _motion_gate_last_time_left + 30.0
    )

    if session_changed or timer_rollback or timer_restarted_from_stop or time_left_jump:
        _motion_gate_active = False
        _motion_gate_block_until = 0.0
        snap["forceStopMusic"] = True
        snap.setdefault("signals", []).append("motion_gate_session_reset")

    _motion_gate_session_key = session_key
    _motion_gate_last_time_ms = current_time_ms
    _motion_gate_last_time_left = session_time_left

    if _motion_gate_active:
        return snap

    now = time.monotonic()
    if _motion_gate_block_until <= 0.0:
        _motion_gate_block_until = now + MOTION_GATE_BLOCK_SECONDS
        snap.setdefault("signals", []).append("motion_gate_armed")

    if now < _motion_gate_block_until:
        snap["stateId"] = "pre_race"
        snap["stateLabel"] = "Attente mouvement"
        snap.setdefault("signals", []).append("motion_gate_block")
        snap["signals"] = sorted(set(snap["signals"]))
        return snap

    if float(snap.get("speedKph", 0.0) or 0.0) >= MOTION_GATE_SPEED_KPH:
        _motion_gate_active = True
        _motion_gate_block_until = 0.0
        snap.setdefault("signals", []).append("motion_gate_released")
        snap["signals"] = sorted(set(snap["signals"]))
        return snap

    snap["stateId"] = "pre_race"
    snap["stateLabel"] = "Attente mouvement"
    snap.setdefault("signals", []).append("motion_gate_wait_speed")
    snap["signals"] = sorted(set(snap["signals"]))
    return snap


def find_process():
    """Retourne le psutil.Process ACC ou None."""
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if (proc.info.get("name") or "").lower() in ACC_EXE_NAMES:
                return proc
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return None


def get_state(precedent: dict | None = None) -> dict:
    """Retourne l'état normalisé ACC pour le tick courant."""
    proc = find_process()
    shm, err = _SRC.read()
    snap = _classify(proc, shm, err)
    snap = _infer_events(snap, precedent)
    return _apply_motion_gate(snap, precedent)
