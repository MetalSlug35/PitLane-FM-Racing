# =============================================================================
#  Bloc3 — ACC_tableau_etats.py
#  Tableau d'export des états ACC — compatible architecture modulaire.
#
#  Ce fichier documente toutes les valeurs possibles de "stateId" produites par
#  ACC_state_monitor.py et leur politique musique recommandée pour le Bloc4.
#
#  TABLEAU_ETATS : liste de dicts, un par état normalisé.
#  POLITIQUE_MUSIQUE : dict {state_id → "play"|"stop"|"hold"|"exit"}
#                      à passer dans config["music_policy_map"] du Coordinateur.
# =============================================================================

TABLEAU_ETATS = [
    {
        "state_id":        "game_closed",
        "label":           "Jeu fermé",
        "politique":       "exit",
        "source_detection": "Aucun processus ACC (acc.exe / ac2-win64-shipping.exe) détecté.",
        "shared_memory":   "N/A",
        "session":         "N/A",
        "flags":           "N/A",
        "notes":           "Déclenche la fermeture de l'app PitLane FM.",
    },
    {
        "state_id":        "loading",
        "label":           "Chargement",
        "politique":       "stop",
        "source_detection": "Processus ACC présent mais shared memory indisponible.",
        "shared_memory":   "mapping_unavailable",
        "session":         "N/A",
        "flags":           "N/A",
        "notes":           "Transitoire au démarrage du jeu.",
    },
    {
        "state_id":        "menus",
        "label":           "Menus",
        "politique":       "stop",
        "source_detection": "graphics.status == ACC_OFF",
        "shared_memory":   "disponible",
        "session":         "*",
        "flags":           "N/A",
        "notes":           "Écrans de menus principaux, garage, lobby.",
    },
    {
        "state_id":        "replay",
        "label":           "Replay",
        "politique":       "stop",
        "source_detection": "graphics.status == ACC_REPLAY",
        "shared_memory":   "disponible",
        "session":         "*",
        "flags":           "N/A",
        "notes":           "",
    },
    {
        "state_id":        "paused",
        "label":           "Pause",
        "politique":       "hold",
        "source_detection": "graphics.status == ACC_PAUSE",
        "shared_memory":   "disponible",
        "session":         "*",
        "flags":           "N/A",
        "notes":           "La musique est conservée si elle jouait déjà, sinon non démarrée.",
    },
    {
        "state_id":        "setup_menu",
        "label":           "Menu setup / garage",
        "politique":       "stop",
        "source_detection": "graphics.is_setup_menu_visible == True",
        "shared_memory":   "disponible",
        "session":         "*",
        "flags":           "N/A",
        "notes":           "Menu setup visible en pit. Peut être précédé de 'paused'.",
    },
    {
        "state_id":        "pre_race",
        "label":           "Grille / avant départ",
        "politique":       "stop",
        "source_detection": "ACC_LIVE + ACC_RACE + global_red=True + global_green=False",
        "shared_memory":   "disponible",
        "session":         "ACC_RACE",
        "flags":           "red=True, green=False",
        "notes":           "Musique bloquée jusqu'au feu vert (depart_course_valide).",
    },
    {
        "state_id":        "race",
        "label":           "En course",
        "politique":       "play",
        "source_detection": "ACC_LIVE + ACC_RACE (hors pit, hors setup, après feu vert)",
        "shared_memory":   "disponible",
        "session":         "ACC_RACE",
        "flags":           "variés",
        "notes":           "Nécessite depart_course_valide=True pour démarrer la musique.",
    },
    {
        "state_id":        "qualifying",
        "label":           "Qualifications",
        "politique":       "play",
        "source_detection": "ACC_LIVE + ACC_QUALIFY",
        "shared_memory":   "disponible",
        "session":         "ACC_QUALIFY",
        "flags":           "*",
        "notes":           "",
    },
    {
        "state_id":        "practice",
        "label":           "Essais",
        "politique":       "play",
        "source_detection": "ACC_LIVE + ACC_PRACTICE",
        "shared_memory":   "disponible",
        "session":         "ACC_PRACTICE",
        "flags":           "*",
        "notes":           "",
    },
    {
        "state_id":        "hotlap",
        "label":           "Hotlap",
        "politique":       "play",
        "source_detection": "ACC_LIVE + ACC_HOTLAP",
        "shared_memory":   "disponible",
        "session":         "ACC_HOTLAP",
        "flags":           "*",
        "notes":           "",
    },
    {
        "state_id":        "hotstint",
        "label":           "Hotstint",
        "politique":       "play",
        "source_detection": "ACC_LIVE + ACC_HOTSTINT",
        "shared_memory":   "disponible",
        "session":         "ACC_HOTSTINT",
        "flags":           "*",
        "notes":           "",
    },
    {
        "state_id":        "time_attack",
        "label":           "Time attack",
        "politique":       "play",
        "source_detection": "ACC_LIVE + ACC_TIME_ATTACK",
        "shared_memory":   "disponible",
        "session":         "ACC_TIME_ATTACK",
        "flags":           "*",
        "notes":           "",
    },
    {
        "state_id":        "pit_lane",
        "label":           "Voie des stands",
        "politique":       "play",
        "source_detection": "graphics.is_in_pit_lane == True",
        "shared_memory":   "disponible",
        "session":         "*",
        "flags":           "*",
        "notes":           "La musique continue en pit lane.",
    },
    {
        "state_id":        "pit_stop",
        "label":           "Stand / arrêt pit",
        "politique":       "play",
        "source_detection": "graphics.is_in_pit == True + is_in_pit_lane == False",
        "shared_memory":   "disponible",
        "session":         "*",
        "flags":           "*",
        "notes":           "",
    },
    {
        "state_id":        "on_track",
        "label":           "En piste (résiduel)",
        "politique":       "play",
        "source_detection": "ACC_LIVE + session inconnue",
        "shared_memory":   "disponible",
        "session":         "autre",
        "flags":           "*",
        "notes":           "Fallback pour sessions non encore mappées.",
    },
    {
        "state_id":        "unknown",
        "label":           "Inconnu",
        "politique":       "stop",
        "source_detection": "Combinaison status/session non classifiée.",
        "shared_memory":   "disponible",
        "session":         "*",
        "flags":           "*",
        "notes":           "",
    },
]

# Politique musique prête à passer au Coordinateur
POLITIQUE_MUSIQUE = {row["state_id"]: row["politique"] for row in TABLEAU_ETATS}

# Événements spéciaux produits par ACC_state_monitor
EVENEMENTS = [
    {
        "event_id":   "garage_return_pause_menu",
        "description": "Transition paused → setup_menu/pit_lane/pit_stop détectée.",
        "effet":      "Verrouille la musique (stop) jusqu'à reprise de la vitesse > 3 km/h.",
    },
    {
        "event_id":   "garage_return_direct",
        "description": "Transition setup_menu → pit_lane/menus détectée.",
        "effet":      "Idem garage_return_pause_menu.",
    },
    {
        "event_id":   "race_start",
        "description": "Apparition green_flag pendant ACC_RACE.",
        "effet":      "Active depart_course_valide → musique autorisée.",
    },
]
