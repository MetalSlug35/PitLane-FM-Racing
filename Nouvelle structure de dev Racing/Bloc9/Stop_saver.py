# =============================================================================
#  Bloc9 - Stop_saver.py
#  Lecture / ecriture de la configuration INI et comptage d'utilisation.
#  Mode notifications unifie:
#    [Notifications] -> volume / switch / playlist / radio / tts_voice
#  Compatibilite lecture:
#    accepte encore les anciennes cles flat_/vr_ si elles existent.
# =============================================================================

import configparser
import json
import os


DEFAULTS = {
    "volume": 0.4,
    "mode": "playlist",
    "radio_courante": "",
    "notifications": True,
    "language": "en",
    "usage_count": 0,
    "donation_popup_shown": False,
    "tts_voice": "",
    "raccourcis": {},
    "notification_settings": {
        "volume": True,
        "switch": True,
        "playlist": True,
        "radio": True,
    },
    "music_folders": [],
    "music_folder": "",
    "radio_folder": "",
}

SUPPORTED_LANGUAGES = ("fr", "en", "de", "it", "es", "pt", "zh", "ja")
_FALLBACK_LANGUAGE = "en"


def _normalize_language(raw: str) -> str:
    raw = (raw or "").replace("-", "_").lower()
    for code in SUPPORTED_LANGUAGES:
        if raw.startswith(code):
            return code
    return _FALLBACK_LANGUAGE


def _default_state() -> dict:
    state = dict(DEFAULTS)
    state["notification_settings"] = dict(DEFAULTS["notification_settings"])
    state["music_folders"] = list(DEFAULTS["music_folders"])
    state["raccourcis"] = {}
    return state


def normalize_music_folders(raw) -> list[str]:
    if raw is None:
        return []

    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        try:
            raw = json.loads(text)
        except Exception:
            raw = [part for part in text.replace("\r", "\n").replace("|", "\n").split("\n")]

    if isinstance(raw, (tuple, list, set)):
        items = list(raw)
    else:
        items = [raw]

    normalized = []
    seen = set()
    for item in items:
        path = str(item or "").strip().strip('"')
        if not path:
            continue
        path = os.path.normpath(os.path.expanduser(os.path.expandvars(path)))
        key = path.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(path)
    return normalized


def _getboolean_optional(section, key):
    try:
        return section.getboolean(key)
    except Exception:
        return None


def _resolve_notification_settings(section, legacy_notifications: bool) -> dict:
    defaults = dict(DEFAULTS["notification_settings"])
    if section is None:
        if not legacy_notifications:
            return {key: False for key in defaults}
        return defaults

    notif = dict(defaults)
    legacy_map = {
        "volume": ("flat_volume",),
        "switch": ("flat_switch", "vr_switch"),
        "playlist": ("flat_playlist", "vr_playlist"),
        "radio": ("flat_radio", "vr_radio"),
    }

    for key, old_keys in legacy_map.items():
        direct = _getboolean_optional(section, key)
        if direct is not None:
            notif[key] = direct
            continue

        legacy_values = [_getboolean_optional(section, old_key) for old_key in old_keys]
        legacy_values = [value for value in legacy_values if value is not None]
        if legacy_values:
            notif[key] = any(legacy_values)

    if not legacy_notifications and not any(
        _getboolean_optional(section, key) is not None
        for key in ("volume", "switch", "playlist", "radio")
    ):
        notif = {key: False for key in notif}

    return notif


def lire(config_file: str) -> dict:
    state = _default_state()

    if not config_file or not os.path.exists(config_file):
        return state

    config = configparser.ConfigParser()
    try:
        config.read(config_file, encoding="utf-8")
    except Exception:
        return state

    if config.has_section("Raccourcis"):
        state["raccourcis"] = dict(config["Raccourcis"])

    legacy_notifications = True
    if config.has_section("Etat"):
        sec = config["Etat"]
        try:
            state["volume"] = max(0.0, min(1.0, sec.getfloat("volume", DEFAULTS["volume"])))
        except Exception:
            pass
        legacy_notifications = sec.getboolean("notifications", True)
        state["notifications"] = legacy_notifications
        mode = sec.get("mode", "playlist")
        state["mode"] = "radio" if mode == "radio" else "playlist"
        rp = sec.get("radio_courante", "")
        state["radio_courante"] = rp if (rp and os.path.exists(rp)) else ""

    if config.has_section("General"):
        sec = config["General"]
        state["language"] = _normalize_language(sec.get("language", _FALLBACK_LANGUAGE))
        try:
            state["usage_count"] = max(0, sec.getint("usage_count", 0))
        except Exception:
            pass
        state["donation_popup_shown"] = sec.getboolean("donation_popup_shown", False)

    notif_section = config["Notifications"] if config.has_section("Notifications") else None
    state["notification_settings"] = _resolve_notification_settings(notif_section, legacy_notifications)
    if notif_section is not None:
        state["tts_voice"] = notif_section.get("tts_voice", "").strip()
    state["notifications"] = any(state["notification_settings"].values())

    if config.has_section("Chemins"):
        sec = config["Chemins"]
        raw_folders = sec.get("music_folders", "").strip()
        folders = normalize_music_folders(raw_folders)
        legacy_folder = sec.get("music_folder", "").strip()
        if legacy_folder:
            folders = normalize_music_folders(folders + [legacy_folder])
        rf = sec.get("radio_folder", "").strip()
        if folders:
            state["music_folders"] = folders
            state["music_folder"] = folders[0]
        if rf:
            state["radio_folder"] = rf

    return state


def sauvegarder(config_file: str, state: dict) -> None:
    if not config_file:
        return

    config = configparser.ConfigParser()
    if os.path.exists(config_file):
        try:
            config.read(config_file, encoding="utf-8")
        except Exception:
            pass

    notif = dict(DEFAULTS["notification_settings"])
    notif.update(state.get("notification_settings", {}))
    notifications_on = any(notif.values())

    if not config.has_section("Etat"):
        config.add_section("Etat")
    config["Etat"]["volume"] = str(round(float(state.get("volume", DEFAULTS["volume"])), 3))
    config["Etat"]["mode"] = state.get("mode", "playlist")
    config["Etat"]["radio_courante"] = state.get("radio_courante", "") or ""
    config["Etat"]["notifications"] = "true" if notifications_on else "false"

    if not config.has_section("General"):
        config.add_section("General")
    config["General"]["language"] = state.get("language", _FALLBACK_LANGUAGE)
    config["General"]["usage_count"] = str(int(state.get("usage_count", 0)))
    config["General"]["donation_popup_shown"] = (
        "true" if state.get("donation_popup_shown", False) else "false"
    )

    if not config.has_section("Notifications"):
        config.add_section("Notifications")
    for key in DEFAULTS["notification_settings"]:
        config["Notifications"][key] = "true" if notif.get(key, False) else "false"
    config["Notifications"]["tts_voice"] = state.get("tts_voice", "") or ""

    music_folders = normalize_music_folders(
        state.get("music_folders") or state.get("music_folder") or ""
    )
    state["music_folders"] = music_folders
    state["music_folder"] = music_folders[0] if music_folders else ""
    if not config.has_section("Chemins"):
        config.add_section("Chemins")
    config["Chemins"]["music_folders"] = json.dumps(music_folders, ensure_ascii=False)
    config["Chemins"]["music_folder"] = state.get("music_folder", "") or ""
    config["Chemins"]["radio_folder"] = state.get("radio_folder", "") or ""

    try:
        os.makedirs(os.path.dirname(config_file), exist_ok=True)
    except Exception:
        pass

    try:
        with open(config_file, "w", encoding="utf-8") as handle:
            config.write(handle)
    except Exception:
        pass


def incrementer_usage(state: dict) -> dict:
    state["usage_count"] = int(state.get("usage_count", 0)) + 1
    return state


def doit_afficher_popup(state: dict, seuil: int = 10) -> bool:
    return (
        int(state.get("usage_count", 0)) >= seuil
        and not state.get("donation_popup_shown", False)
    )
