# =============================================================================
#  Bloc6 — music_player.py
#  Lecteur audio unifié via miniaudio (playlist MP3/WAV + radio HTTP).
#  Module universel — aucune dépendance à un jeu spécifique.
#
#  API publique :
#    configure(music_folders, radio_folder, norm_target_rms, fade_duration,
#              fade_steps, on_track_started, on_track_ended)
#    set_volume(level)          — 0.0 à 1.0
#    get_volume() -> float
#    start_volume_ramp(direction)  — "up" / "down" (continu)
#    stop_volume_ramp()
#    adjust_volume_step(direction) — incrément unique
#    lancer()                   — démarre la lecture (playlist ou radio)
#    arreter(fade=False)        — arrête la lecture
#    piste_suivante()           — piste suivante (playlist) / radio suivante
#    switcher_mode()            — bascule playlist ↔ radio
#    get_mode() -> str          — "playlist" ou "radio"
#    get_radio_courante() -> str
#    set_radio(path)
#    est_en_lecture() -> bool
# =============================================================================

import os
import random
import threading
import struct as _struct
import urllib.request

import miniaudio

try:
    from mutagen.id3 import ID3, TIT2, TPE1
    MUTAGEN_OK = True
except ImportError:
    MUTAGEN_OK = False


# ─────────────────────────────────────────────────────────────────────────────
#  CONSTANTES AUDIO
# ─────────────────────────────────────────────────────────────────────────────
SAMPLE_FORMAT    = miniaudio.SampleFormat.SIGNED16
NCHANNELS        = 2
SAMPLE_RATE      = 44100
BYTES_PER_FRAME  = 4   # 2 canaux × 2 octets


# ─────────────────────────────────────────────────────────────────────────────
#  ÉTAT INTERNE
# ─────────────────────────────────────────────────────────────────────────────
_music_folders    = []
_radio_folder     = ""
_norm_target_rms  = 0.55
_fade_duration    = 3.0
_fade_steps       = 40

_volume           = 0.4
_volume_ramp_dir  = None    # "up" / "down" / None
_volume_step      = 0.01
_volume_repeat    = 0.1

_mode_radio       = False
_radio_courante   = None
_playlist_restante = []

_device       = None
_stop_event   = threading.Event()
_session_id   = 0
_response     = None   # connexion HTTP radio active

_lecture_en_cours = False
_piste_terminee   = False
_fade_mult        = 1.0
_fade_en_cours    = False

_radio_intro_mult  = 1.0
_radio_intro_token = 0
_radio_intro_duck_enabled = False

# Callbacks
_on_track_started = None   # callable(titre, artiste, mode)
_on_track_ended   = None   # callable()

_last_command_time = 0.0
_last_track_time   = 0.0


# ─────────────────────────────────────────────────────────────────────────────
#  CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────
def _normalize_music_folder_list(music_folders=None, music_folder: str = "") -> list[str]:
    if music_folders is None:
        music_folders = []
    if isinstance(music_folders, str):
        music_folders = [music_folders]
    elif isinstance(music_folders, (tuple, set)):
        music_folders = list(music_folders)
    elif not isinstance(music_folders, list):
        music_folders = [music_folders] if music_folders else []
    if music_folder:
        music_folders = list(music_folders) + [music_folder]

    normalized = []
    seen = set()
    for entry in music_folders:
        path = str(entry or "").strip().strip('"')
        if not path:
            continue
        path = os.path.normpath(os.path.expanduser(os.path.expandvars(path)))
        key = path.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(path)
    return normalized


def configure(
    music_folders=None,
    music_folder: str = "",
    radio_folder: str = "",
    norm_target_rms: float = 0.55,
    fade_duration: float = 3.0,
    fade_steps: int = 40,
    volume_step: float = 0.01,
    volume_repeat: float = 0.1,
    on_track_started=None,
    on_track_ended=None,
) -> None:
    """Configure les chemins et paramètres du lecteur."""
    global _music_folders, _radio_folder, _norm_target_rms
    global _fade_duration, _fade_steps, _volume_step, _volume_repeat
    global _on_track_started, _on_track_ended, _playlist_restante
    _music_folders   = _normalize_music_folder_list(music_folders, music_folder)
    _radio_folder    = radio_folder or ""
    _norm_target_rms = norm_target_rms
    _fade_duration   = fade_duration
    _fade_steps      = fade_steps
    _volume_step     = volume_step
    _volume_repeat   = volume_repeat
    _on_track_started = on_track_started if callable(on_track_started) else None
    _on_track_ended   = on_track_ended   if callable(on_track_ended)   else None
    _playlist_restante = []


def set_radio_intro_duck(enabled: bool) -> None:
    """Memorise si l'intro radio doit etre mutee puis fadee apres le TTS."""
    global _radio_intro_duck_enabled
    _radio_intro_duck_enabled = bool(enabled)


def begin_radio_tts_duck() -> int:
    """
    Coupe immediatement la radio pour laisser passer un TTS.
    Retourne un token permettant de relancer le fade uniquement pour
    la demande la plus recente.
    """
    global _radio_intro_token, _radio_intro_mult
    _radio_intro_token += 1
    _radio_intro_mult = 0.0
    return _radio_intro_token


# ─────────────────────────────────────────────────────────────────────────────
#  VOLUME
# ─────────────────────────────────────────────────────────────────────────────
def set_volume(level: float) -> None:
    global _volume
    _volume = max(0.0, min(1.0, level))


def get_volume() -> float:
    return _volume


def start_volume_ramp(direction: str) -> None:
    """Démarre une rampe de volume continue ("up" / "down")."""
    global _volume_ramp_dir
    _volume_ramp_dir = direction

    def _boucle():
        global _volume, _volume_ramp_dir
        while _volume_ramp_dir == direction:
            _volume = (
                min(1.0, _volume + _volume_step)
                if direction == "up"
                else max(0.0, _volume - _volume_step)
            )
            threading.Event().wait(_volume_repeat)
    threading.Thread(target=_boucle, name="VolumeRamp", daemon=True).start()


def stop_volume_ramp() -> None:
    global _volume_ramp_dir
    _volume_ramp_dir = None


def adjust_volume_step(direction: str) -> None:
    global _volume
    _volume = (
        min(1.0, _volume + _volume_step)
        if direction == "up"
        else max(0.0, _volume - _volume_step)
    )


# ─────────────────────────────────────────────────────────────────────────────
#  PROTECTION COMMANDES TROP RAPIDES
# ─────────────────────────────────────────────────────────────────────────────
import time as _time


def _commande_trop_rapide(delai: float = 0.8) -> bool:
    global _last_command_time
    now = _time.time()
    if now - _last_command_time < delai:
        return True
    _last_command_time = now
    return False


# ─────────────────────────────────────────────────────────────────────────────
#  LISTE DES FICHIERS
# ─────────────────────────────────────────────────────────────────────────────
def lister_musiques() -> list:
    if not _music_folders:
        return []
    fichiers = []
    seen = set()
    radio_abs = os.path.abspath(_radio_folder) if _radio_folder else None
    for music_folder in _music_folders:
        if not os.path.exists(music_folder):
            continue
        for root, dirs, files in os.walk(music_folder):
            if radio_abs:
                dirs[:] = [d for d in dirs if os.path.abspath(os.path.join(root, d)) != radio_abs]
            for f in files:
                if not f.lower().endswith((".mp3", ".wav")):
                    continue
                full_path = os.path.normpath(os.path.join(root, f))
                key = os.path.abspath(full_path).lower()
                if key in seen:
                    continue
                seen.add(key)
                fichiers.append(full_path)
    return fichiers


def lister_radios() -> list:
    if not os.path.exists(_radio_folder):
        return []
    return [
        os.path.join(_radio_folder, f)
        for f in sorted(os.listdir(_radio_folder))
        if f.lower().endswith((".m3u", ".m3u8", ".pls"))
    ]


def choisir_musique() -> str | None:
    """Shuffle intelligent — parcourt toute la playlist avant de recommencer."""
    global _playlist_restante
    tous = lister_musiques()
    if not tous:
        return None
    if not _playlist_restante:
        _playlist_restante = tous[:]
        random.shuffle(_playlist_restante)
    return _playlist_restante.pop()


def lire_fichier_radio(path: str) -> str | None:
    """Extrait l'URL depuis un fichier .m3u / .m3u8 / .pls."""
    try:
        ext = os.path.splitext(path)[1].lower()
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                if ext == ".pls":
                    if line.lower().startswith("file") and "=" in line:
                        return line.split("=", 1)[1].strip()
                elif not line.startswith("#"):
                    return line
    except Exception:
        pass
    return None


def lire_tags(path: str) -> tuple:
    """Retourne (titre, artiste) depuis les tags ID3, fallback nom de fichier."""
    titre, artiste = "", ""
    if MUTAGEN_OK:
        try:
            tags = ID3(path)
            if TIT2 in tags:
                titre = str(tags[TIT2])
            if TPE1 in tags:
                artiste = str(tags[TPE1])
        except Exception:
            pass
    if not titre:
        import re as _re
        nom = os.path.splitext(os.path.basename(path))[0]
        nom = nom.replace("_-_", " - ").replace("_", " ").strip()
        nom = _re.sub(r"^\d+\s*[-\.]\s*", "", nom).strip()
        if " - " in nom:
            parts = nom.split(" - ", 1)
            artiste, titre = parts[0].strip(), parts[1].strip()
        else:
            titre = nom
    return titre, artiste


# ─────────────────────────────────────────────────────────────────────────────
#  GÉNÉRATEURS MINIAUDIO
# ─────────────────────────────────────────────────────────────────────────────
def _gen_playlist(path: str, ma_session: int):
    """Générateur miniaudio pour fichier local avec normalisation RMS."""
    global _piste_terminee
    _piste_terminee = False
    stream = miniaudio.stream_file(
        path,
        output_format=SAMPLE_FORMAT,
        nchannels=NCHANNELS,
        sample_rate=SAMPLE_RATE,
        frames_to_read=1024,
    )
    next(stream)
    required = yield b""
    while not _stop_event.is_set() and ma_session == _session_id:
        try:
            chunk = stream.send(required)
        except StopIteration:
            _piste_terminee = True
            return
        data = bytes(chunk)
        ns = len(data) // 2
        if ns > 0:
            samples = list(_struct.unpack(f"{ns}h", data))
            rms = (sum(s * s for s in samples) / ns) ** 0.5 / 32767.0
            gain = min(_norm_target_rms / rms, 4.0) if rms > 0.001 else 1.0
            vol = _volume * _fade_mult * gain
            if abs(vol - 1.0) > 0.001:
                data = _struct.pack(
                    f"{ns}h",
                    *(max(-32768, min(32767, int(s * vol))) for s in samples),
                )
        required = yield data


def _gen_radio(url: str, ma_session: int):
    """Générateur miniaudio pour stream HTTP avec normalisation RMS."""
    CHUNK  = 16 * 1024
    DECODE = 32 * 1024
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "WinampMPEG/5.0"})
        global _response
        _response = urllib.request.urlopen(req, timeout=30)
        buf_raw = b""
        buf_pcm = b""
        required = yield b""
        while not _stop_event.is_set() and ma_session == _session_id:
            while len(buf_raw) < DECODE and not _stop_event.is_set():
                try:
                    data = _response.read(CHUNK)
                    if not data:
                        return
                    buf_raw += data
                except Exception:
                    return
            if _stop_event.is_set():
                return
            try:
                decoded = miniaudio.decode(
                    buf_raw[:DECODE],
                    output_format=SAMPLE_FORMAT,
                    nchannels=NCHANNELS,
                    sample_rate=SAMPLE_RATE,
                )
                buf_raw = buf_raw[DECODE:]
                buf_pcm += bytes(decoded.samples)
            except Exception:
                buf_raw = buf_raw[CHUNK:]
            while len(buf_pcm) >= required * BYTES_PER_FRAME:
                if _stop_event.is_set():
                    return
                n = required * BYTES_PER_FRAME
                chunk = buf_pcm[:n]
                buf_pcm = buf_pcm[n:]
                ns = len(chunk) // 2
                if ns > 0:
                    samples = list(_struct.unpack(f"{ns}h", chunk))
                    rms = (sum(s * s for s in samples) / ns) ** 0.5 / 32767.0
                    gain = min(_norm_target_rms / rms, 4.0) if rms > 0.001 else 1.0
                    vol = _volume * _fade_mult * _radio_intro_mult * gain
                    if abs(vol - 1.0) > 0.001:
                        chunk = _struct.pack(
                            f"{ns}h",
                            *(max(-32768, min(32767, int(s * vol))) for s in samples),
                        )
                required = yield chunk
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
#  GESTION DEVICE MINIAUDIO
# ─────────────────────────────────────────────────────────────────────────────
def _demarrer_device(gen):
    global _device
    device = miniaudio.PlaybackDevice(
        output_format=SAMPLE_FORMAT,
        nchannels=NCHANNELS,
        sample_rate=SAMPLE_RATE,
        buffersize_msec=120,
    )
    _device = device
    device.start(gen)
    return device


def _arreter_interne():
    global _session_id, _device, _response, _fade_mult
    global _radio_intro_mult, _radio_intro_token
    _fade_mult = 1.0
    _radio_intro_mult = 1.0
    _radio_intro_token += 1
    _session_id += 1
    _stop_event.set()
    if _device:
        try:
            _device.stop()
            _device.close()
        except Exception:
            pass
        _device = None
    if _response:
        try:
            _response.close()
        except Exception:
            pass
        _response = None


# ─────────────────────────────────────────────────────────────────────────────
#  FADE OUT
# ─────────────────────────────────────────────────────────────────────────────
def _fade_out_et_arreter():
    global _fade_mult, _fade_en_cours
    if _fade_en_cours:
        return
    _fade_en_cours = True

    def _fade():
        global _fade_mult, _fade_en_cours
        step_delay = _fade_duration / _fade_steps
        for i in range(_fade_steps):
            if _stop_event.is_set():
                break
            _fade_mult = 1.0 - (i + 1) / _fade_steps
            _time.sleep(step_delay)
        _fade_mult = 0.0
        _arreter_interne()
        _fade_en_cours = False

    threading.Thread(target=_fade, name="FadeOut", daemon=True).start()


# ─────────────────────────────────────────────────────────────────────────────
#  FADE IN RADIO (duck intro pour TTS)
# ─────────────────────────────────────────────────────────────────────────────
def _start_radio_intro_fade(token: int):
    def _fade():
        global _radio_intro_mult
        steps = 30
        delay = 3.0 / steps
        for i in range(steps):
            if token != _radio_intro_token or not _mode_radio:
                return
            _radio_intro_mult = (i + 1) / steps
            _time.sleep(delay)
        if token == _radio_intro_token and _mode_radio:
            _radio_intro_mult = 1.0
    threading.Thread(target=_fade, name="RadioIntroFade", daemon=True).start()


def radio_intro_fade_callback():
    """À passer en on_complete du TTS lors d'un démarrage radio."""
    global _radio_intro_token
    _start_radio_intro_fade(_radio_intro_token)


def end_radio_tts_duck(token: int | None = None) -> None:
    """
    Relance doucement la radio apres un TTS.
    Si un token est fourni, seule la demande correspondante peut relancer le fade.
    """
    if token is None:
        token = _radio_intro_token
    _start_radio_intro_fade(token)


# ─────────────────────────────────────────────────────────────────────────────
#  API PUBLIQUE — CONTRÔLE LECTURE
# ─────────────────────────────────────────────────────────────────────────────
def est_en_lecture() -> bool:
    return _device is not None and _device.running


def get_mode() -> str:
    return "radio" if _mode_radio else "playlist"


def get_radio_courante() -> str:
    return _radio_courante or ""


def set_radio(path: str) -> None:
    global _radio_courante
    _radio_courante = path if (path and os.path.exists(path)) else None


def arreter(fade: bool = False) -> None:
    global _lecture_en_cours
    stop_volume_ramp()
    _lecture_en_cours = False
    if fade:
        _fade_out_et_arreter()
    else:
        _stop_event.set()
        _arreter_interne()


def lancer(duck_for_vr=None) -> None:
    """
    Démarre la lecture.
    duck_for_vr=True → atténue l'intro radio pour laisser passer le TTS.
    Si None, réutilise la préférence mémorisée.
    """
    global _mode_radio, _radio_courante, _lecture_en_cours
    global _session_id, _fade_mult, _radio_intro_mult, _radio_intro_token
    global _radio_intro_duck_enabled

    if duck_for_vr is None:
        duck_for_vr = _radio_intro_duck_enabled
    else:
        _radio_intro_duck_enabled = bool(duck_for_vr)
        duck_for_vr = _radio_intro_duck_enabled

    if _lecture_en_cours:
        return
    _lecture_en_cours = True
    _arreter_interne()
    _fade_mult = 1.0
    _stop_event.clear()
    ma_session = _session_id

    if _mode_radio:
        _radio_intro_mult = 1.0
        if not _radio_courante or not os.path.exists(_radio_courante):
            radios = lister_radios()
            if not radios:
                _mode_radio = False
                _lecture_en_cours = False
                lancer(duck_for_vr)
                return
            _radio_courante = radios[0]

        url = lire_fichier_radio(_radio_courante)
        if not url:
            _mode_radio = False
            _lecture_en_cours = False
            lancer(duck_for_vr)
            return

        def _start_radio():
            global _lecture_en_cours, _radio_intro_mult, _radio_intro_token, _mode_radio
            try:
                if duck_for_vr:
                    token = begin_radio_tts_duck()
                else:
                    token = _radio_intro_token
                    _radio_intro_mult = 1.0

                g = _gen_radio(url, ma_session)
                next(g)
                nom = os.path.splitext(os.path.basename(_radio_courante))[0]

                def _start_device_after_tts():
                    global _lecture_en_cours, _mode_radio
                    if ma_session != _session_id or not _mode_radio:
                        return
                    try:
                        _demarrer_device(g)
                        if duck_for_vr:
                            end_radio_tts_duck(token)
                        _lecture_en_cours = False
                    except Exception:
                        if ma_session == _session_id:
                            _mode_radio = False
                            _lecture_en_cours = False
                            lancer()

                if duck_for_vr:
                    if _on_track_started:
                        try:
                            _on_track_started(nom, "", "radio", _start_device_after_tts)
                        except Exception:
                            _start_device_after_tts()
                    else:
                        _start_device_after_tts()
                else:
                    _demarrer_device(g)
                    if _on_track_started:
                        try:
                            _on_track_started(nom, "", "radio", None)
                        except Exception:
                            pass
                    _lecture_en_cours = False
            except Exception:
                if ma_session == _session_id:
                    _mode_radio = False
                    _lecture_en_cours = False
                    lancer()

        threading.Thread(target=_start_radio, name="StartRadio", daemon=True).start()

    else:
        musique = choisir_musique()
        if not musique:
            radios = lister_radios()
            if radios:
                _mode_radio = True
                if not _radio_courante or not os.path.exists(_radio_courante):
                    _radio_courante = radios[0]
                _lecture_en_cours = False
                if _on_track_started:
                    try:
                        _on_track_started("", "", "switch_to_radio", None)
                    except Exception:
                        pass
                lancer(duck_for_vr)
            else:
                _lecture_en_cours = False
            return

        def _start_playlist():
            global _lecture_en_cours
            try:
                g = _gen_playlist(musique, ma_session)
                next(g)
                _demarrer_device(g)
                titre, artiste = lire_tags(musique)
                if _on_track_started:
                    try:
                        _on_track_started(titre, artiste, "playlist", None)
                    except Exception:
                        pass
                _lecture_en_cours = False
            except Exception:
                if ma_session == _session_id:
                    _lecture_en_cours = False
                    lancer()

        threading.Thread(target=_start_playlist, name="StartPlaylist", daemon=True).start()


def piste_suivante() -> None:
    global _radio_courante
    if _commande_trop_rapide():
        return
    now = _time.time()
    global _last_track_time
    if now - _last_track_time < 1.0:
        return
    _last_track_time = now

    if _mode_radio:
        if _radio_intro_duck_enabled:
            begin_radio_tts_duck()
        arreter()
        radios = lister_radios()
        if radios:
            idx = (radios.index(_radio_courante) + 1) % len(radios) if _radio_courante in radios else 0
            _radio_courante = radios[idx]
        lancer()
    else:
        arreter()
        lancer()


def switcher_mode(on_switch_notification=None) -> None:
    """Bascule playlist ↔ radio."""
    global _mode_radio, _radio_courante
    if _commande_trop_rapide():
        return
    if _mode_radio and _radio_intro_duck_enabled:
        begin_radio_tts_duck()
    arreter()
    if not _mode_radio:
        radios = lister_radios()
        if not radios:
            if on_switch_notification:
                try:
                    on_switch_notification("radio_folder_empty")
                except Exception:
                    pass
            lancer()
            return
        _mode_radio = True
        if not _radio_courante or not os.path.exists(_radio_courante):
            _radio_courante = radios[0]
        if on_switch_notification:
            try:
                on_switch_notification("switch_to_radio")
            except Exception:
                pass
    else:
        _mode_radio = False
        if on_switch_notification:
            try:
                on_switch_notification("switch_to_playlist")
            except Exception:
                pass
    lancer()


# ─────────────────────────────────────────────────────────────────────────────
#  TICK (à appeler dans la boucle principale)
# ─────────────────────────────────────────────────────────────────────────────
def tick() -> None:
    """
    À appeler à chaque itération de la boucle principale (~0.8 s).
    Gère la piste terminée en playlist (déclenche la suivante automatiquement).
    """
    global _piste_terminee
    if _piste_terminee and not _lecture_en_cours and not _mode_radio:
        _piste_terminee = False
        lancer()
