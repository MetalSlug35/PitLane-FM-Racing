# =============================================================================
#  Bloc3 — ACE_state_monitor.py
#  Surveillance de l'état du jeu Assetto Corsa EVO (ACE).
#  Utilise la shared memory ACC-like (pyaccsharedmemory) + parsing log ACE.
#
#  API publique (interface normalisée Bloc3) :
#    find_process() -> psutil.Process | None
#    get_state(precedent: dict | None) -> dict
#
#  Logique embarquée spécifique ACE :
#    - musique_session_active  : la musique ne démarre qu'après que la voiture
#                                a réellement bougé dans la session courante.
#    - depart_course_valide    : en session ACC_RACE, la musique reste bloquée
#                                tant qu'aucun mouvement vitesse n'a été vu.
#    - Gate pit_lane / pit_stop : la musique est suspendue tant que la voiture
#                                est à l'arrêt au stand (speed < 3 km/h).
#
#  Quand le gate bloque, get_state() retourne stateId="pre_race" au lieu de
#  l'état réel, ce qui entraîne politique="stop" dans le coordinateur.
# =============================================================================

from __future__ import annotations

import atexit
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path

import psutil

try:
    from pyaccsharedmemory import (
        ACC_FLAG_TYPE,
        ACC_SESSION_TYPE,
        ACC_STATUS,
        accSharedMemory,
        read_graphics_map,
        read_physic_map,
        read_static_map,
    )
    _SHMEM_OK = True
except Exception:
    ACC_FLAG_TYPE = ACC_SESSION_TYPE = ACC_STATUS = None
    accSharedMemory = read_graphics_map = read_physic_map = read_static_map = None
    _SHMEM_OK = False


ACE_EXE_NAMES = frozenset(("assettocorsaevo.exe",))
ACE_LOG_CANDIDATES = (
    Path.home() / "Saved Games" / "ACE" / "log.txt",
    Path.home() / "Documents" / "ACE" / "log.txt",
)
_SHMEM_SAMPLE_INTERVAL = 0.05

# Politique locale (miroir de ACE_tableau_etats.POLITIQUE_MUSIQUE).
# Utilisée uniquement par le gate interne — ne pas modifier ici.
_POLITIQUE_LOCALE = {
    "game_closed": "exit",
    "loading":     "stop",
    "menus":       "stop",
    "pre_race":    "stop",
    "race":        "play",
    "qualifying":  "play",
    "practice":    "play",
    "paused":      "hold",
    "setup_menu":  "stop",
    "pit_lane":    "play",
    "pit_stop":    "play",
    "on_track":    "play",
    "replay":      "stop",
    "unknown":     "stop",
}

# ─────────────────────────────────────────────────────────────────────────────
#  REGEX LOG
# ─────────────────────────────────────────────────────────────────────────────
_TS_RE            = re.compile(r"^\[(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})\]")
_LAST_UI_RE       = re.compile(r"Last ui url loaded coui://uiresources/(?P<page>[^\s]+)", re.IGNORECASE)
_LOADING_PAGE_RE  = re.compile(
    r"Loading page\s+(?P<page>[^\s]+)\s+(?P<route>.*?)\s+transition:",
    re.IGNORECASE,
)
_TRACK_RE         = re.compile(r"Creating physics track:\s*(?P<track>.+?)\s*$", re.IGNORECASE)
_SESSION_PHASE_RE = re.compile(r"setSessionPhase\s+(?P<phase>[A-Za-z0-9_]+)", re.IGNORECASE)

MENU_PAGES         = ("menu.html", "singleplayer.html", "intro.html")
PAUSE_ROUTE_TOKENS = ("pause",)
PIT_ROUTE_TOKENS   = ("pitlane",)
PRE_RACE_PHASES    = {
    "waiting_for_players",
    "start_spawn_on_position",
    "start_countdown_no_lights",
    "start_countdown_lights_on",
}
RACE_RELEASE_PHASES = {
    "session",
    "overtime_waiting_for_leader",
    "overtime_waiting_for_others",
}


# ─────────────────────────────────────────────────────────────────────────────
#  SHARED MEMORY (ACC-like)
# ─────────────────────────────────────────────────────────────────────────────
class _ACCLikeSharedSource:
    def __init__(self):
        self._reader = None
        self._lock = threading.Lock()
        self._thread = None
        self._stop_evt = threading.Event()
        self._last_payload = None
        self._last_error = "mapping_unavailable"
        self._latches = self._new_latches()

    @staticmethod
    def _new_latches() -> dict:
        return {
            "max_speed_kmh": 0.0,
            "max_current_time_ms": 0,
            "max_normalized_delta": 0.0,
            "baseline_normalized_pos": None,
            "movement_seen": False,
            "release_speed_seen": False,
            "green_seen": False,
            "red_seen": False,
            "pit_lane_seen": False,
            "pit_stop_seen": False,
        }

    def _ensure_sampler(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_evt.clear()
        self._thread = threading.Thread(
            target=self._sample_loop,
            name="ACE-SharedMemory-Sampler",
            daemon=True,
        )
        self._thread.start()

    def _sample_loop(self) -> None:
        while not self._stop_evt.is_set():
            with self._lock:
                if self._reader is not None:
                    self._read_once_locked()
            self._stop_evt.wait(_SHMEM_SAMPLE_INTERVAL)

    def _connect(self) -> bool:
        if not _SHMEM_OK:
            return False
        with self._lock:
            if self._reader is not None:
                return True
            try:
                self._reader = accSharedMemory()
                self._last_error = ""
                self._ensure_sampler()
                return True
            except Exception:
                self._reader = None
                self._last_error = "mapping_unavailable"
                return False

    def _update_latches_locked(self, physics, graphics) -> None:
        speed_kmh = float(getattr(physics, "speed_kmh", 0.0) or 0.0)
        current_time_ms = int(getattr(graphics, "current_time", 0) or 0)
        normalized_pos = float(getattr(graphics, "normalized_car_position", 0.0) or 0.0)

        baseline = self._latches.get("baseline_normalized_pos")
        if baseline is None:
            baseline = normalized_pos
            self._latches["baseline_normalized_pos"] = baseline
        delta = abs(normalized_pos - baseline)

        self._latches["max_speed_kmh"] = max(self._latches["max_speed_kmh"], speed_kmh)
        self._latches["max_current_time_ms"] = max(self._latches["max_current_time_ms"], current_time_ms)
        self._latches["max_normalized_delta"] = max(self._latches["max_normalized_delta"], delta)

        if (
            speed_kmh >= 5.0
            or delta >= 0.0015
            or (speed_kmh >= 3.0 and current_time_ms >= 2000)
        ):
            self._latches["movement_seen"] = True
        if speed_kmh >= 5.0:
            self._latches["release_speed_seen"] = True

        if _SHMEM_OK and ACC_FLAG_TYPE is not None:
            if graphics.flag == ACC_FLAG_TYPE.ACC_GREEN_FLAG or bool(getattr(graphics, "global_green", False)):
                self._latches["green_seen"] = True
            if graphics.flag == ACC_FLAG_TYPE.ACC_YELLOW_FLAG or bool(getattr(graphics, "global_yellow", False)):
                pass
            if graphics.flag == ACC_FLAG_TYPE.ACC_WHITE_FLAG or bool(getattr(graphics, "global_white", False)):
                pass
            if graphics.flag == ACC_FLAG_TYPE.ACC_CHECKERED_FLAG or bool(getattr(graphics, "global_chequered", False)):
                pass
        if bool(getattr(graphics, "global_red", False)):
            self._latches["red_seen"] = True
        if bool(getattr(graphics, "is_in_pit_lane", False)):
            self._latches["pit_lane_seen"] = True
        if bool(getattr(graphics, "is_in_pit", False)):
            self._latches["pit_stop_seen"] = True

    def _read_once_locked(self) -> bool:
        if self._reader is None:
            self._last_payload = None
            self._last_error = "mapping_unavailable"
            return False
        try:
            physics = read_physic_map(self._reader.physicSM)
            graphics = read_graphics_map(self._reader.graphicSM)
            statics = read_static_map(self._reader.staticSM)
        except Exception as exc:
            try:
                self._reader.close()
            except Exception:
                pass
            self._reader = None
            self._last_payload = None
            self._last_error = f"read_failed:{exc}"
            return False

        if ACC_STATUS is None or ACC_SESSION_TYPE is None:
            self._last_payload = None
            self._last_error = "enum_unavailable"
            return False

        valid_status = {m.value for m in ACC_STATUS}
        valid_sessions = {m.value for m in ACC_SESSION_TYPE}
        try:
            if graphics.status.value not in valid_status:
                self._last_payload = None
                self._last_error = "invalid_status"
                return False
            if graphics.session_type.value not in valid_sessions:
                self._last_payload = None
                self._last_error = "invalid_session_type"
                return False
        except Exception:
            self._last_payload = None
            self._last_error = "invalid_shared_content"
            return False

        self._update_latches_locked(physics, graphics)
        self._last_payload = {"physics": physics, "graphics": graphics, "static": statics}
        self._last_error = ""
        return True

    def read(self) -> tuple[dict | None, str]:
        if not self._connect():
            return None, self._last_error or "mapping_unavailable"
        with self._lock:
            if self._last_payload is None and not self._read_once_locked():
                return None, self._last_error or "mapping_unavailable"
            payload = dict(self._last_payload)
            payload["_latches"] = dict(self._latches)
            return payload, self._last_error

    def reset_latches(self) -> None:
        with self._lock:
            self._latches = self._new_latches()

    def close(self) -> None:
        with self._lock:
            if self._reader is not None:
                try:
                    self._reader.close()
                except Exception:
                    pass
            self._reader = None
            self._last_payload = None
            self._last_error = "mapping_unavailable"
            self._latches = self._new_latches()


# ─────────────────────────────────────────────────────────────────────────────
#  TRACKING INCRÉMENTAL DU LOG ACE
# ─────────────────────────────────────────────────────────────────────────────
class _ACELogTracker:
    def __init__(self, paths: tuple[Path, ...]):
        self._paths    = tuple(paths)
        self.path      = self._resolve_path()
        self.position  = 0
        self._sig      = None   # (pid, create_time)
        self.state: dict = {}
        self._reset_state()

    def _resolve_path(self) -> Path:
        existing = []
        for candidate in self._paths:
            try:
                if candidate.exists():
                    existing.append((candidate.stat().st_mtime, candidate))
            except Exception:
                pass
        if existing:
            existing.sort(key=lambda item: item[0], reverse=True)
            return existing[0][1]
        return self._paths[0]

    def _reset_state(self) -> None:
        self.state = {
            "current_ui_page":              "",
            "current_ui_route":             "",
            "current_ui_ts":                0.0,
            "last_loading_page":            "",
            "last_loading_route":           "",
            "last_loading_ts":              0.0,
            "last_session_start_ts":        0.0,
            "last_pitlane_ts":              0.0,
            "last_replay_ts":               0.0,
            "last_menu_ts":                 0.0,
            "last_pause_ts":                0.0,
            "last_hud_ts":                  0.0,
            "last_track_name":              "",
            "last_track_ts":                0.0,
            "last_grid_ts":                 0.0,
            "last_countdown_no_lights_ts":  0.0,
            "last_lights_on_ts":            0.0,
            "last_lights_off_ts":           0.0,
            "last_session_phase":           "",
            "last_session_phase_ts":        0.0,
            "last_session_live_ts":         0.0,
            "last_split_ts":                0.0,
        }

    def _update_sig(self, proc) -> None:
        resolved_path = self._resolve_path()
        if proc is None:
            sig = None
        else:
            try:
                sig = (proc.pid, round(proc.create_time(), 3))
            except Exception:
                sig = None
        if sig != self._sig or resolved_path != self.path:
            self._sig     = sig
            self.path     = resolved_path
            self.position = 0
            self._reset_state()
            self._bootstrap(proc)

    def _cutoff(self, proc) -> float:
        if proc is None:
            return 0.0
        try:
            return max(0.0, proc.create_time() - 5.0)
        except Exception:
            return 0.0

    def _bootstrap(self, proc) -> None:
        if not self.path.exists():
            return
        try:
            size  = self.path.stat().st_size
            start = max(0, size - 768 * 1024)
            with self.path.open("rb") as fh:
                fh.seek(start)
                if start:
                    fh.readline()
                chunk = fh.read().decode("utf-8", errors="ignore")
            for line in chunk.splitlines():
                self._apply(line, proc)
            self.position = size
        except Exception:
            pass

    def _apply(self, line: str, proc) -> None:
        m_ts = _TS_RE.match(line)
        if m_ts:
            try:
                line_ts = datetime.strptime(m_ts.group("ts"), "%Y-%m-%d %H:%M:%S.%f").timestamp()
                if line_ts < self._cutoff(proc):
                    return
            except Exception:
                pass

        ts      = time.time()
        lowered = line.lower()

        m = _LAST_UI_RE.search(line)
        if m:
            page = m.group("page").strip().lstrip("/")
            self.state["current_ui_page"]  = page
            self.state["current_ui_ts"]    = ts
            route = self.state.get("last_loading_route", "") or ""
            self.state["current_ui_route"] = route
            if page == "hud.html":
                self.state["last_hud_ts"] = ts
            elif page == "ingame.html" and any(t in route for t in PAUSE_ROUTE_TOKENS):
                self.state["last_pause_ts"] = ts
            elif page in MENU_PAGES or page == "settings.html":
                self.state["last_menu_ts"] = ts

        m = _LOADING_PAGE_RE.search(line)
        if m:
            page  = m.group("page").strip().lstrip("/")
            route = m.group("route").strip()
            self.state["last_loading_page"]  = page
            self.state["last_loading_route"] = route
            self.state["last_loading_ts"]    = ts
            if page in MENU_PAGES or page == "settings.html":
                self.state["last_menu_ts"] = ts
            if page == "ingame.html" and any(t in route for t in PAUSE_ROUTE_TOKENS):
                self.state["last_pause_ts"] = ts

        m = _TRACK_RE.search(line)
        if m:
            self.state["last_track_name"] = m.group("track").strip()
            self.state["last_track_ts"]   = ts

        m = _SESSION_PHASE_RE.search(line)
        if m:
            phase  = m.group("phase").strip()
            pl     = phase.lower()
            self.state["last_session_phase"]    = phase
            self.state["last_session_phase_ts"] = ts
            if pl in PRE_RACE_PHASES:
                # Nouvelle phase de départ : on oublie toute ancienne libération
                # de course pour ne pas autoriser la musique trop tôt.
                self.state["last_session_live_ts"] = 0.0
                self.state["last_split_ts"] = 0.0
            if pl == "start_countdown_no_lights":
                self.state["last_countdown_no_lights_ts"] = ts
            elif pl == "start_countdown_lights_on":
                self.state["last_lights_on_ts"] = ts
            elif pl == "start_countdown_lights_off":
                self.state["last_lights_off_ts"] = ts
            elif pl in RACE_RELEASE_PHASES:
                self.state["last_session_live_ts"] = ts

        if "starting session" in lowered:
            self.state["last_session_start_ts"] = ts
            self.state["last_loading_ts"]        = ts
            self.state["last_session_live_ts"]   = 0.0
            self.state["last_split_ts"]          = 0.0
            self.state["last_lights_off_ts"]     = 0.0

        if (
            "showloadingmodal" in lowered
            or "curtain loading" in lowered
            or "changing physics engine, shutting down" in lowered
            or "creating physics track" in lowered
            or "gamemodechangeeventwithlockedphysics" in lowered
            or "executeservergamemodechangedeventwithphysicslock" in lowered
        ):
            self.state["last_loading_ts"] = ts

        if "exited to pitlane" in lowered:
            self.state["last_pitlane_ts"] = ts

        if "race grid:" in lowered or "startingpositiontype_grid" in lowered:
            self.state["last_grid_ts"] = ts

        if "[gameplay]" in lowered and "on split" in lowered:
            self.state["last_split_ts"] = ts

        if "[replay]" in lowered or "replay saved" in lowered or "saving replay" in lowered:
            self.state["last_replay_ts"] = ts

        if (
            "entering singleplayer" in lowered
            or "rootpage singleplayerpage" in lowered
            or "last ui url loaded coui://uiresources/menu.html" in lowered
            or "last ui url loaded coui://uiresources/singleplayer.html" in lowered
            or "last ui url loaded coui://uiresources/intro.html" in lowered
        ):
            self.state["last_menu_ts"] = ts

    def poll(self, proc) -> dict:
        self._update_sig(proc)
        if not self.path.exists():
            return dict(self.state)
        try:
            size = self.path.stat().st_size
            if size < self.position:
                self.position = 0
                self._reset_state()
                self._bootstrap(proc)
                return dict(self.state)
            with self.path.open("r", encoding="utf-8", errors="ignore") as fh:
                fh.seek(self.position)
                for line in fh:
                    self._apply(line.rstrip("\n"), proc)
                self.position = fh.tell()
        except Exception:
            pass
        return dict(self.state)


# ─────────────────────────────────────────────────────────────────────────────
#  INSTANCES GLOBALES
# ─────────────────────────────────────────────────────────────────────────────
_SRC = _ACCLikeSharedSource()
_LOG = _ACELogTracker(ACE_LOG_CANDIDATES)
atexit.register(_SRC.close)

# Drapeaux de gate (persistants entre les ticks)
_musique_session_active = False
_depart_course_valide   = False
_pre_race_exit_block_until = 0.0
_require_current_release_speed = False


def _reset_gate_flags() -> None:
    global _musique_session_active, _depart_course_valide
    global _pre_race_exit_block_until, _require_current_release_speed
    _musique_session_active = False
    _depart_course_valide = False
    _pre_race_exit_block_until = 0.0
    _require_current_release_speed = False
    _SRC.reset_latches()


def _arm_pre_race_release_block(duration: float = 2.0) -> None:
    global _pre_race_exit_block_until, _require_current_release_speed
    _pre_race_exit_block_until = max(_pre_race_exit_block_until, time.monotonic() + max(0.0, float(duration)))
    _require_current_release_speed = True


# ─────────────────────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def _enum_name(v) -> str:
    return getattr(v, "name", str(v))


def _recent(ts: float, seconds: float) -> bool:
    return bool(ts) and (time.time() - ts) <= seconds


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value or 0)
    except Exception:
        return default


def _clear_latched_fields(snap: dict) -> None:
    current_speed = float(snap.get("speed_kmh", 0.0) or 0.0)
    current_time = _safe_int(snap.get("current_time_ms", 0))
    signals = set(snap.get("signals", []))
    snap["latched_max_speed_kmh"] = current_speed
    snap["latched_current_time_ms"] = current_time
    snap["latched_max_normalized_delta"] = 0.0
    snap["latched_movement_seen"] = current_speed >= 5.0
    snap["latched_release_speed_seen"] = current_speed >= 5.0
    snap["latched_green_seen"] = "green_flag" in signals
    snap["latched_red_seen"] = "red_flag" in signals


def _should_reset_gate(precedent: dict | None, merged: dict) -> bool:
    if precedent is None:
        return False

    current_state = str(merged.get("state_id", "unknown") or "unknown")
    previous_state = str(precedent.get("stateId", "unknown") or "unknown")
    current_speed_kph = float(merged.get("speed_kmh", 0.0) or 0.0)
    current_signals = set(merged.get("signals", []))

    if current_state in {"game_closed", "loading", "menus", "setup_menu", "replay"}:
        return True

    current_track = str(merged.get("track", "") or "").strip().lower()
    previous_track = str(precedent.get("_raw_track", "") or "").strip().lower()
    if current_track and previous_track and current_track != previous_track:
        return True

    current_time_ms = _safe_int(merged.get("current_time_ms", 0))
    previous_time_ms = _safe_int(precedent.get("_raw_current_time_ms", 0))
    if previous_time_ms > 5000 and current_time_ms >= 0 and current_time_ms + 2000 < previous_time_ms:
        return True

    if (
        previous_state == "paused"
        and (
            current_state == "pre_race"
            or "pre_race_log" in current_signals
        )
        and current_time_ms <= 5000
        and current_speed_kph < 5.0
    ):
        return True

    if previous_state not in {"game_closed", "loading", "menus", "setup_menu", "replay"} and current_state in {
        "menus",
        "loading",
        "setup_menu",
        "replay",
    }:
        return True

    return False


# ─────────────────────────────────────────────────────────────────────────────
#  CONSTRUCTION SNAPSHOT ACC-LIKE
# ─────────────────────────────────────────────────────────────────────────────
def _build_acc_like_snapshot(shm: dict) -> dict:
    physics  = shm["physics"]
    graphics = shm["graphics"]
    statics  = shm["static"]
    latches  = dict(shm.get("_latches", {}) or {})

    snap = {
        "state_id":              "unknown",
        "state_label":           "Inconnu",
        "status":                _enum_name(graphics.status),
        "session_type":          _enum_name(graphics.session_type),
        "is_in_pit":             bool(getattr(graphics, "is_in_pit", False)),
        "is_in_pit_lane":        bool(getattr(graphics, "is_in_pit_lane", False)),
        "is_setup_menu_visible": bool(getattr(graphics, "is_setup_menu_visible", False)),
        "flag":                  _enum_name(graphics.flag),
        "track":                 str(getattr(statics, "track", "") or "").strip(),
        "track_configuration":   str(getattr(statics, "track_configuration", "") or "").strip(),
        "car_model":             str(getattr(statics, "car_model", "") or "").strip(),
        "active_cars":           int(getattr(graphics, "active_cars", 0) or 0),
        "current_time_ms":       int(getattr(graphics, "current_time", 0) or 0),
        "session_time_left":     float(getattr(graphics, "session_time_left", 0.0) or 0.0),
        "speed_kmh":             float(getattr(physics, "speed_kmh", 0.0) or 0.0),
        "normalized_pos":        float(getattr(graphics, "normalized_car_position", 0.0) or 0.0),
        "latched_max_speed_kmh": float(latches.get("max_speed_kmh", 0.0) or 0.0),
        "latched_current_time_ms": _safe_int(latches.get("max_current_time_ms", 0)),
        "latched_max_normalized_delta": float(latches.get("max_normalized_delta", 0.0) or 0.0),
        "latched_movement_seen": bool(latches.get("movement_seen", False)),
        "latched_release_speed_seen": bool(latches.get("release_speed_seen", False)),
        "latched_green_seen": bool(latches.get("green_seen", False)),
        "latched_red_seen": bool(latches.get("red_seen", False)),
        "signals":               [],
    }

    signals = []
    if _SHMEM_OK and ACC_FLAG_TYPE is not None:
        if graphics.flag == ACC_FLAG_TYPE.ACC_GREEN_FLAG or bool(getattr(graphics, "global_green", False)):
            signals.append("green_flag")
        if graphics.flag == ACC_FLAG_TYPE.ACC_YELLOW_FLAG or bool(getattr(graphics, "global_yellow", False)):
            signals.append("yellow_flag")
        if graphics.flag == ACC_FLAG_TYPE.ACC_WHITE_FLAG or bool(getattr(graphics, "global_white", False)):
            signals.append("white_flag")
        if graphics.flag == ACC_FLAG_TYPE.ACC_CHECKERED_FLAG or bool(getattr(graphics, "global_chequered", False)):
            signals.append("chequered_flag")
    if bool(getattr(graphics, "global_red", False)):
        signals.append("red_flag")
    if snap["is_in_pit_lane"]:
        signals.append("pit_lane")
    if snap["is_in_pit"]:
        signals.append("pit_stop")
    snap["signals"] = sorted(set(signals))

    if not (_SHMEM_OK and ACC_STATUS is not None):
        return snap

    status       = graphics.status
    session_type = graphics.session_type

    if status == ACC_STATUS.ACC_OFF:
        snap["state_id"], snap["state_label"] = "menus", "Menus"
    elif status == ACC_STATUS.ACC_REPLAY:
        snap["state_id"], snap["state_label"] = "replay", "Replay"
    elif status == ACC_STATUS.ACC_PAUSE:
        snap["state_id"], snap["state_label"] = "paused", "Pause"
    elif snap["is_setup_menu_visible"]:
        snap["state_id"], snap["state_label"] = "setup_menu", "Menu setup"
    elif snap["is_in_pit_lane"]:
        snap["state_id"], snap["state_label"] = "pit_lane", "Voie des stands"
    elif snap["is_in_pit"]:
        snap["state_id"], snap["state_label"] = "pit_stop", "Stand"
    elif status == ACC_STATUS.ACC_LIVE and session_type == ACC_SESSION_TYPE.ACC_RACE:
        snap["state_id"], snap["state_label"] = "race", "En course"
    elif status == ACC_STATUS.ACC_LIVE and session_type == ACC_SESSION_TYPE.ACC_QUALIFY:
        snap["state_id"], snap["state_label"] = "qualifying", "Qualifications"
    elif status == ACC_STATUS.ACC_LIVE and session_type == ACC_SESSION_TYPE.ACC_PRACTICE:
        snap["state_id"], snap["state_label"] = "practice", "Essais"
    elif status == ACC_STATUS.ACC_LIVE:
        snap["state_id"], snap["state_label"] = "on_track", "En session"

    return snap


# ─────────────────────────────────────────────────────────────────────────────
#  CONSTRUCTION SNAPSHOT LOG-ONLY
# ─────────────────────────────────────────────────────────────────────────────
def _build_log_snapshot(log: dict) -> dict:
    page  = str(log.get("current_ui_page", "") or "").strip().lstrip("/")
    route = str(log.get("current_ui_route", "") or "").lower()
    last_loading_page = str(log.get("last_loading_page", "") or "").strip().lstrip("/").lower()
    last_loading_route = str(log.get("last_loading_route", "") or "").lower()

    snap = {
        "state_id":              "unknown",
        "state_label":           "Inconnu",
        "status":                "ACE_OFF",
        "session_type":          "ACE_SESSION_UNKNOWN",
        "is_in_pit":             False,
        "is_in_pit_lane":        False,
        "is_setup_menu_visible": False,
        "flag":                  "ACE_FLAG_UNKNOWN",
        "track":                 str(log.get("last_track_name", "") or "").strip(),
        "track_configuration":   "",
        "car_model":             "",
        "active_cars":           0,
        "current_time_ms":       0,
        "session_time_left":     0.0,
        "speed_kmh":             0.0,
        "normalized_pos":        0.0,
        "latched_max_speed_kmh": 0.0,
        "latched_current_time_ms": 0,
        "latched_max_normalized_delta": 0.0,
        "latched_movement_seen": False,
        "latched_release_speed_seen": False,
        "latched_green_seen": False,
        "latched_red_seen": False,
        "signals":               [],
    }

    loading_recent      = _recent(log.get("last_loading_ts", 0.0), 8.0)
    pitlane_recent      = _recent(log.get("last_pitlane_ts", 0.0), 12.0)
    replay_recent       = _recent(log.get("last_replay_ts", 0.0), 8.0)
    session_recent      = _recent(log.get("last_session_start_ts", 0.0), 900.0)
    pause_recent        = _recent(log.get("last_pause_ts", 0.0), 4.0)
    grid_recent         = _recent(log.get("last_grid_ts", 0.0), 180.0)
    countdown_recent    = (
        _recent(log.get("last_countdown_no_lights_ts", 0.0), 120.0)
        or _recent(log.get("last_lights_on_ts", 0.0), 120.0)
    )
    lights_off_recent   = _recent(log.get("last_lights_off_ts", 0.0), 8.0)
    session_live_recent = _recent(log.get("last_session_live_ts", 0.0), 20.0)
    split_recent        = _recent(log.get("last_split_ts", 0.0), 30.0)

    session_phase   = str(log.get("last_session_phase", "") or "").lower()
    pre_race_phase  = session_phase in PRE_RACE_PHASES
    race_release    = session_phase in RACE_RELEASE_PHASES or session_live_recent or split_recent
    pre_race_active = (grid_recent or countdown_recent or pre_race_phase) and not race_release
    track_active    = race_release or (lights_off_recent and session_live_recent) or split_recent
    if page == "hud.html":
        snap["status"] = "ACE_LIVE"
        if pre_race_active:
            snap["state_id"], snap["state_label"] = "pre_race", "Grille / avant départ"
            snap["signals"] = ["hud_page", "pre_race_log"]
        else:
            snap["state_id"], snap["state_label"] = "on_track", "En session"
            snap["signals"] = ["hud_page"] + (["race_release_log"] if track_active else [])

    elif page == "ingame.html":
        snap["status"] = "ACE_LIVE"
        if any(t in route for t in PAUSE_ROUTE_TOKENS):
            snap["state_id"], snap["state_label"] = "paused", "Pause"
            snap["signals"] = ["pause_page"]
        elif any(t in route for t in PIT_ROUTE_TOKENS) or pitlane_recent:
            snap["is_in_pit_lane"] = True
            if pre_race_active:
                snap["state_id"], snap["state_label"] = "pre_race", "Grille / avant départ"
                snap["signals"] = ["pit_lane_page", "pre_race_log"]
            else:
                snap["state_id"], snap["state_label"] = "pit_lane", "Voie des stands"
                snap["signals"] = ["pit_lane_page"] + (["race_release_log"] if track_active else [])
        else:
            if pre_race_active:
                snap["state_id"], snap["state_label"] = "pre_race", "Grille / avant départ"
                snap["signals"] = ["ingame_page", "pre_race_log"]
            else:
                snap["state_id"], snap["state_label"] = "on_track", "En session"
                snap["signals"] = ["ingame_page"] + (["race_release_log"] if track_active else [])

    elif page == "settings.html":
        if session_recent:
            snap["status"] = "ACE_PAUSE"
            snap["state_id"], snap["state_label"] = "paused", "Pause"
            snap["signals"] = ["settings_page"]
        else:
            snap["status"] = "ACE_MENU"
            snap["state_id"], snap["state_label"] = "menus", "Menus"
            snap["signals"] = ["settings_page"]

    elif page in MENU_PAGES or page.endswith("showroom.html"):
        snap["status"] = "ACE_MENU"
        snap["state_id"], snap["state_label"] = "menus", "Menus"
        snap["signals"] = ["menu_page"]

    elif replay_recent:
        snap["status"] = "ACE_REPLAY"
        snap["state_id"], snap["state_label"] = "replay", "Replay"
        snap["signals"] = ["replay_log"]

    elif loading_recent:
        snap["status"] = "ACE_LOADING"
        snap["state_id"], snap["state_label"] = "loading", "Chargement"
        snap["signals"] = ["loading_log"]

    elif session_recent or pitlane_recent:
        snap["status"] = "ACE_LIVE"
        if pre_race_active:
            snap["state_id"], snap["state_label"] = "pre_race", "Grille / avant départ"
            snap["signals"] = ["session_log", "pre_race_log"]
        elif pitlane_recent:
            snap["is_in_pit_lane"] = True
            snap["state_id"], snap["state_label"] = "pit_lane", "Voie des stands"
            snap["signals"] = ["pit_lane_log"] + (["race_release_log"] if track_active else [])
        else:
            snap["state_id"], snap["state_label"] = "on_track", "En session"
            snap["signals"] = ["session_log"] + (["race_release_log"] if track_active else [])

    snap["signals"] = sorted(set(snap["signals"]))
    return snap


# ─────────────────────────────────────────────────────────────────────────────
#  FUSION DES DEUX SOURCES
# ─────────────────────────────────────────────────────────────────────────────
def _merge(shm_snap: dict, log_snap: dict) -> dict:
    merged  = dict(shm_snap)
    log_id  = log_snap.get("state_id", "unknown")
    shm_id  = shm_snap.get("state_id", "unknown")
    shm_sig = set(shm_snap.get("signals", []))
    log_sig = set(log_snap.get("signals", []))

    blocking = {"menus", "loading", "pre_race", "paused", "replay", "setup_menu"}
    if log_id in blocking:
        if log_id == "loading" and "loading_log" not in log_sig:
            pass
        elif log_id == "pre_race":
            speed = max(
                float(shm_snap.get("speed_kmh", 0.0) or 0.0),
                float(shm_snap.get("latched_max_speed_kmh", 0.0) or 0.0),
            )
            current_ms = max(
                int(shm_snap.get("current_time_ms", 0) or 0),
                int(shm_snap.get("latched_current_time_ms", 0) or 0),
            )
            has_release = bool(shm_snap.get("latched_release_speed_seen", False)) or speed >= 5.0
            if not has_release:
                merged["state_id"] = log_id
                merged["state_label"] = log_snap.get("state_label", shm_snap.get("state_label", "Inconnu"))
                merged["status"] = log_snap.get("status", shm_snap.get("status", ""))
                merged["session_type"] = log_snap.get("session_type", shm_snap.get("session_type", ""))
        else:
            merged["state_id"]    = log_id
            merged["state_label"] = log_snap.get("state_label", shm_snap.get("state_label", "Inconnu"))
            if log_id in {"pre_race", "setup_menu", "paused", "replay"}:
                merged["status"]       = log_snap.get("status", shm_snap.get("status", ""))
                merged["session_type"] = log_snap.get("session_type", shm_snap.get("session_type", ""))

    elif shm_id in {"race", "on_track", "pit_lane"} and log_id == "pit_lane":
        speed = max(
            float(shm_snap.get("speed_kmh", 0.0) or 0.0),
            float(shm_snap.get("latched_max_speed_kmh", 0.0) or 0.0),
        )
        has_release = bool(shm_snap.get("latched_release_speed_seen", False)) or speed >= 5.0
        if not has_release:
            merged["state_id"]    = "pre_race"
            merged["state_label"] = "Grille / avant départ"
            merged["status"]       = log_snap.get("status", shm_snap.get("status", ""))
            merged["session_type"] = log_snap.get("session_type", shm_snap.get("session_type", ""))

    merged["signals"] = sorted(shm_sig | log_sig)
    return merged


# ─────────────────────────────────────────────────────────────────────────────
#  INFÉRENCE D'ÉVÉNEMENTS
# ─────────────────────────────────────────────────────────────────────────────
def _infer_events(snap: dict, precedent: dict | None) -> dict:
    snap.setdefault("events", [])
    snap.setdefault("raceStartInferred", False)
    snap.setdefault("greenLightInferred", False)

    if precedent is None:
        return snap

    events       = []
    prev_id      = precedent.get("stateId", "")
    cur_id       = snap.get("stateId", "")
    sigs         = set(snap.get("signals", []))
    prev_sig     = set(precedent.get("signals", []))
    prev_time_ms = _safe_int(precedent.get("currentTimeMs", 0))
    cur_time_ms  = _safe_int(snap.get("currentTimeMs", 0))
    cur_speed    = float(snap.get("speedKph", 0.0) or 0.0)

    if not precedent.get("_process_running") and snap.get("_process_running"):
        events.append("game_launched")
    if prev_id != cur_id:
        events.append("state_changed")
    if not precedent.get("_raw_pit_lane") and snap.get("_raw_pit_lane"):
        events.append("pit_entry")
    if precedent.get("_raw_pit_lane") and not snap.get("_raw_pit_lane"):
        events.append("pit_exit")
    if not precedent.get("_raw_pit_stop") and snap.get("_raw_pit_stop"):
        events.append("pit_stop")
    if prev_id != "replay" and cur_id == "replay":
        events.append("replay_detected")
    if prev_id == "paused" and cur_id in {"setup_menu", "pit_lane", "pit_stop"}:
        events.append("garage_return_pause_menu")
    if (
        prev_id == "paused"
        and cur_id in {"pre_race", "race", "on_track"}
        and (cur_id == "pre_race" or "pre_race_log" in sigs)
        and cur_speed < 5.0
        and (
            cur_time_ms <= 5000
            or (prev_time_ms > 5000 and cur_time_ms + 2000 < prev_time_ms)
        )
    ):
        events.append("session_restart_pause_menu")
    if prev_id == "setup_menu" and cur_id in {"pit_lane", "pit_stop", "menus"}:
        events.append("garage_return_direct")

    if "green_flag" in sigs and "green_flag" not in prev_sig and cur_id == "race":
        events.append("race_start")
        snap["raceStartInferred"]  = True
        snap["greenLightInferred"] = True

    snap["events"] = sorted(set(events))
    return snap


# ─────────────────────────────────────────────────────────────────────────────
#  GATE MUSIQUE SPÉCIFIQUE ACE
# ─────────────────────────────────────────────────────────────────────────────
def _apply_gate(state_id: str, speed_kph: float, session_type: str,
                signals: set, events: set, current_time_ms: int,
                race_start_inferred: bool, green_light_inferred: bool,
                latched_max_speed_kmh: float, latched_current_time_ms: int,
                latched_movement_seen: bool, latched_release_speed_seen: bool, latched_green_seen: bool,
                latched_red_seen: bool, latched_max_normalized_delta: float,
                is_first_call: bool) -> str:
    """
    Applique la logique de validation de démarrage propre à ACE.

    Retourne le stateId effectif :
      - Si le gate passe     → retourne state_id inchangé
      - Si le gate bloque    → retourne "pre_race" (politique = "stop")

    Effets de bord : met à jour _musique_session_active et _depart_course_valide.
    """
    global _musique_session_active, _depart_course_valide
    global _pre_race_exit_block_until, _require_current_release_speed

    politique = _POLITIQUE_LOCALE.get(state_id, "stop")

    if state_id in {"game_closed", "loading", "menus", "setup_menu", "replay"}:
        _reset_gate_flags()
        return state_id

    if state_id == "pre_race":
        _musique_session_active = False
        _depart_course_valide = False
        return state_id

    # ── Pause à l'arrêt : invalider la session musique ───────────────────────
    if state_id == "paused" and speed_kph < 3.0:
        _musique_session_active = False

    now = time.monotonic()
    if (
        politique == "play"
        and _pre_race_exit_block_until > 0.0
        and now < _pre_race_exit_block_until
    ):
        _musique_session_active = False
        _depart_course_valide = False
        return "pre_race"

    effective_speed_kph = max(float(speed_kph or 0.0), float(latched_max_speed_kmh or 0.0))
    effective_current_time_ms = max(_safe_int(current_time_ms), _safe_int(latched_current_time_ms))
    current_release_speed_seen = bool(float(speed_kph or 0.0) >= 5.0)
    if _require_current_release_speed:
        effective_release_speed_seen = current_release_speed_seen
    else:
        effective_release_speed_seen = bool(
            latched_release_speed_seen
            or effective_speed_kph >= 5.0
        )
    effective_movement_seen = bool(
        latched_movement_seen
        or effective_speed_kph >= 5.0
        or float(latched_max_normalized_delta or 0.0) >= 0.0015
    )

    # ── Mise à jour depart_course_valide (seulement en session ACC_RACE) ─────
    if session_type != "ACC_RACE":
        _depart_course_valide = False
    else:
        if effective_release_speed_seen:
            _depart_course_valide = True
            _require_current_release_speed = False
        elif (
            is_first_call
            and state_id in ("race", "on_track", "pit_lane")
            and (
                effective_speed_kph >= 20.0
                or effective_current_time_ms >= 45000
            )
        ):
            # App lancée en plein milieu d'une course déjà commencée
            _depart_course_valide = True
            _require_current_release_speed = False

    # ── États non "play" : pas de gate, mais reset session si "stop" ─────────
    if politique != "play":
        if politique == "stop":
            _musique_session_active = False
        return state_id

    # ── Gate lecture_live_valide ──────────────────────────────────────────────
    if state_id in ("pit_lane", "pit_stop"):
        # Retour au stand / sortie de pause : tant que la nouvelle session
        # n'a pas été relancée par un vrai mouvement, on garde le blocage.
        lecture_live_valide = _musique_session_active or effective_release_speed_seen
    elif not _musique_session_active:
        if session_type == "ACC_RACE":
            lecture_live_valide = _depart_course_valide
        else:
            # Entraînement / quali (et cas ACE mal étiqueté en practice) :
            # on n'autorise la musique qu'après une vraie vitesse vue en piste.
            lecture_live_valide = effective_release_speed_seen
    else:
        # Session déjà validée → laisser passer
        lecture_live_valide = True

    if lecture_live_valide:
        _musique_session_active = True
        _require_current_release_speed = False
        return state_id
    else:
        _musique_session_active = False
        return "pre_race"   # Bloqué → force politique="stop"


# ─────────────────────────────────────────────────────────────────────────────
#  CONVERSION AU FORMAT NORMALISÉ BLOC3
# ─────────────────────────────────────────────────────────────────────────────
def _to_normalized(proc, snap: dict, effective_state_id: str) -> dict:
    pit_mode = "PIT_NONE"
    if snap.get("is_in_pit_lane"):
        pit_mode = "PIT_LANE"
    elif snap.get("is_in_pit"):
        pit_mode = "PIT_STOP"

    return {
        "stateId":                  effective_state_id,
        "stateLabel":               snap.get("state_label", "Inconnu"),
        "gameState":                snap.get("status", ""),
        "sessionState":             snap.get("session_type", ""),
        "raceState":                snap.get("state_id", "unknown").upper(),
        "pitMode":                  pit_mode,
        "flagColour":               snap.get("flag", ""),
        "speedKph":                 round(float(snap.get("speed_kmh", 0.0) or 0.0), 1),
        "currentTimeMs":            int(snap.get("current_time_ms", 0) or 0),
        "rawNormalizedCarPosition": float(snap.get("normalized_pos", 0.0) or 0.0),
        "signals":                  list(snap.get("signals", [])),
        "events":                   [],
        "raceStartInferred":        False,
        "greenLightInferred":       False,
        # Champs privés pour l'inférence d'événements au tick suivant
        "_process_running":         proc is not None,
        "_raw_pit_lane":            bool(snap.get("is_in_pit_lane", False)),
        "_raw_pit_stop":            bool(snap.get("is_in_pit", False)),
        "_raw_track":               str(snap.get("track", "") or ""),
        "_raw_current_time_ms":     int(snap.get("current_time_ms", 0) or 0),
    }


# ─────────────────────────────────────────────────────────────────────────────
#  API PUBLIQUE
# ─────────────────────────────────────────────────────────────────────────────
def find_process():
    for proc in psutil.process_iter(["pid", "name", "create_time"]):
        try:
            if (proc.info.get("name") or "").lower() in ACE_EXE_NAMES:
                return proc
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return None


def get_state(precedent: dict | None = None) -> dict:
    proc = find_process()

    if proc is None:
        _SRC.close()
        _reset_gate_flags()
        snap = {
            "state_id":    "game_closed",
            "state_label": "Jeu fermé",
            "status":      "",
            "session_type": "",
            "is_in_pit":   False,
            "is_in_pit_lane": False,
            "signals":     [],
        }
        result = _to_normalized(None, snap, "game_closed")
        _infer_events(result, precedent)
        return result

    log = _LOG.poll(proc)
    shm, _err = _SRC.read()

    if shm is not None:
        shm_snap = _build_acc_like_snapshot(shm)
    else:
        shm_snap = {
            "state_id":              "loading",
            "state_label":           "Chargement",
            "status":                "",
            "session_type":          "",
            "is_in_pit":             False,
            "is_in_pit_lane":        False,
            "is_setup_menu_visible": False,
            "flag":                  "",
            "track":                 "",
            "track_configuration":   "",
            "car_model":             "",
            "active_cars":           0,
            "current_time_ms":       0,
            "session_time_left":     0.0,
            "speed_kmh":             0.0,
            "normalized_pos":        0.0,
            "signals":               [],
        }

    log_snap = _build_log_snapshot(log)
    merged   = _merge(shm_snap, log_snap)

    if _should_reset_gate(precedent, merged):
        _reset_gate_flags()
        _clear_latched_fields(merged)

    # Conversion en format normalisé (stateId encore brut à ce stade)
    result = _to_normalized(proc, merged, merged.get("state_id", "unknown"))

    # Inférence d'événements (enrichit result avec events, raceStartInferred…)
    _infer_events(result, precedent)

    force_reset_transition = "session_restart_pause_menu" in set(result.get("events", []))
    if force_reset_transition:
        _reset_gate_flags()
        _clear_latched_fields(merged)
        merged["state_id"] = "pre_race"
        merged["state_label"] = "Grille / avant départ"
        merged["status"] = "ACE_LOADING"
    result["forceStopMusic"] = force_reset_transition

    previous_raw_state = str(precedent.get("raceState", "") or "").strip().lower() if precedent else ""
    current_raw_state = str(merged.get("state_id", "") or "").strip().lower()
    if (
        not force_reset_transition
        and previous_raw_state == "pre_race"
        and current_raw_state in {"race", "on_track", "pit_lane", "pit_stop", "practice", "qualifying"}
    ):
        _arm_pre_race_release_block(2.0)

    # Gate musique : peut substituer stateId par "pre_race" si la musique
    # ne doit pas encore démarrer dans cette session
    effective_id = _apply_gate(
        state_id            = merged.get("state_id", "unknown"),
        speed_kph           = merged.get("speed_kmh", 0.0),
        session_type        = merged.get("session_type", ""),
        signals             = set(result.get("signals", [])),
        events              = set(result.get("events", [])),
        current_time_ms     = merged.get("current_time_ms", 0),
        race_start_inferred = result.get("raceStartInferred", False),
        green_light_inferred= result.get("greenLightInferred", False),
        latched_max_speed_kmh = merged.get("latched_max_speed_kmh", 0.0),
        latched_current_time_ms = merged.get("latched_current_time_ms", 0),
        latched_movement_seen = merged.get("latched_movement_seen", False),
        latched_release_speed_seen = merged.get("latched_release_speed_seen", False),
        latched_green_seen = merged.get("latched_green_seen", False),
        latched_red_seen = merged.get("latched_red_seen", False),
        latched_max_normalized_delta = merged.get("latched_max_normalized_delta", 0.0),
        is_first_call       = precedent is None,
    )
    result["stateId"] = effective_id
    if effective_id == "pre_race":
        result["stateLabel"] = "Grille / avant départ"

    return result
