# =============================================================================
#  Bloc3 — LMU_tableau_etats.py
#  Tableau d'export des états LMU — compatible architecture modulaire.
#  LMU est basé sur rFactor 2 et utilise sa propre shared memory "LMU_Data".
# =============================================================================

TABLEAU_ETATS = [
    {
        "state_id":        "game_closed",
        "label":           "Jeu fermé",
        "politique":       "exit",
        "source_detection": "Aucun processus lemansultimate.exe / lmu.exe détecté.",
        "shared_memory":   "N/A",
        "notes":           "",
    },
    {
        "state_id":        "loading",
        "label":           "Chargement",
        "politique":       "stop",
        "source_detection": "Processus présent, shared memory indisponible ou invalide.",
        "shared_memory":   "mapping_unavailable",
        "notes":           "",
    },
    {
        "state_id":        "menus",
        "label":           "Menus",
        "politique":       "stop",
        "source_detection": "graphics.status == ACC_OFF",
        "shared_memory":   "ACC_OFF",
        "notes":           "",
    },
    {
        "state_id":        "replay",
        "label":           "Replay",
        "politique":       "stop",
        "source_detection": "graphics.status == ACC_REPLAY",
        "shared_memory":   "ACC_REPLAY",
        "notes":           "",
    },
    {
        "state_id":        "paused",
        "label":           "Pause",
        "politique":       "hold",
        "source_detection": "graphics.status == ACC_PAUSE",
        "shared_memory":   "ACC_PAUSE",
        "notes":           "",
    },
    {
        "state_id":        "setup_menu",
        "label":           "Menu setup / garage",
        "politique":       "stop",
        "source_detection": "graphics.is_setup_menu_visible == True",
        "shared_memory":   "ACC_LIVE",
        "notes":           "",
    },
    {
        "state_id":        "pre_race",
        "label":           "Grille / avant départ",
        "politique":       "stop",
        "source_detection": "ACC_LIVE + ACC_RACE + global_red=True + global_green=False",
        "shared_memory":   "ACC_LIVE",
        "notes":           "",
    },
    {
        "state_id":        "race",
        "label":           "En course",
        "politique":       "play",
        "source_detection": "ACC_LIVE + ACC_RACE (hors pit, hors setup)",
        "shared_memory":   "ACC_LIVE + ACC_RACE",
        "notes":           "",
    },
    {
        "state_id":        "qualifying",
        "label":           "Qualifications",
        "politique":       "play",
        "source_detection": "ACC_LIVE + ACC_QUALIFY",
        "shared_memory":   "ACC_LIVE + ACC_QUALIFY",
        "notes":           "",
    },
    {
        "state_id":        "practice",
        "label":           "Essais",
        "politique":       "play",
        "source_detection": "ACC_LIVE + ACC_PRACTICE",
        "shared_memory":   "ACC_LIVE + ACC_PRACTICE",
        "notes":           "",
    },
    {
        "state_id":        "hotlap",
        "label":           "Hotlap",
        "politique":       "play",
        "source_detection": "ACC_LIVE + ACC_HOTLAP",
        "shared_memory":   "ACC_LIVE + ACC_HOTLAP",
        "notes":           "",
    },
    {
        "state_id":        "hotstint",
        "label":           "Hotstint",
        "politique":       "play",
        "source_detection": "ACC_LIVE + ACC_HOTSTINT",
        "shared_memory":   "ACC_LIVE + ACC_HOTSTINT",
        "notes":           "",
    },
    {
        "state_id":        "time_attack",
        "label":           "Time attack",
        "politique":       "play",
        "source_detection": "ACC_LIVE + ACC_TIME_ATTACK",
        "shared_memory":   "ACC_LIVE + ACC_TIME_ATTACK",
        "notes":           "",
    },
    {
        "state_id":        "pit_lane",
        "label":           "Voie des stands",
        "politique":       "play",
        "source_detection": "is_in_pit_lane == True",
        "shared_memory":   "ACC_LIVE",
        "notes":           "",
    },
    {
        "state_id":        "pit_stop",
        "label":           "Stand",
        "politique":       "play",
        "source_detection": "is_in_pit == True + is_in_pit_lane == False",
        "shared_memory":   "ACC_LIVE",
        "notes":           "",
    },
    {
        "state_id":        "on_track",
        "label":           "En piste (résiduel)",
        "politique":       "play",
        "source_detection": "ACC_LIVE + session non classifiée",
        "shared_memory":   "ACC_LIVE",
        "notes":           "",
    },
    {
        "state_id":        "unknown",
        "label":           "Inconnu",
        "politique":       "stop",
        "source_detection": "Combinaison non classifiée.",
        "shared_memory":   "*",
        "notes":           "",
    },
]

POLITIQUE_MUSIQUE = {row["state_id"]: row["politique"] for row in TABLEAU_ETATS}

EVENEMENTS = [
    {
        "event_id":   "garage_return_pause_menu",
        "description": "paused → setup_menu/pit_lane/pit_stop",
        "effet":      "Verrouille la musique.",
    },
    {
        "event_id":   "garage_return_direct",
        "description": "setup_menu → pit_lane/menus",
        "effet":      "Idem.",
    },
    {
        "event_id":   "race_start",
        "description": "green_flag détecté pendant race.",
        "effet":      "Autorise la musique en course.",
    },
]
