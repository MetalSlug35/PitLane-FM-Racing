# =============================================================================
#  Bloc8 - TTS_player.py
#  Lecteur TTS vocal via SAPI Windows.
#  Version robuste: un worker unique, mais une annonce = un sous-processus.
#  Cela permet de tuer proprement un Speak() qui se fige.
# =============================================================================

import atexit
import multiprocessing as mp
import queue
import threading
import time

try:
    import comtypes
    import comtypes.client
    COMTYPES_OK = True
except Exception:
    comtypes = None
    COMTYPES_OK = False


TTS_TEXTS = {
    "switch_to_radio": {
        "fr": "Passage en mode radio.",
        "en": "Switching to radio mode.",
        "de": "Wechsel in den Radiomodus.",
        "it": "Passaggio alla modalita radio.",
        "es": "Cambiando al modo radio.",
        "pt": "A mudar para o modo radio.",
        "zh": "正在切换到电台模式。",
        "ja": "ラジオモードに切り替えます。",
    },
    "switch_to_playlist": {
        "fr": "Passage en mode playlist.",
        "en": "Switching to playlist mode.",
        "de": "Wechsel in den Playlist-Modus.",
        "it": "Passaggio alla modalita playlist.",
        "es": "Cambiando al modo lista de lectura.",
        "pt": "A mudar para o modo playlist.",
        "zh": "正在切换到播放列表模式。",
        "ja": "プレイリストモードに切り替えます。",
    },
    "radio_now": {
        "fr": "Radio {name}.",
        "en": "Radio {name}.",
        "de": "Radio {name}.",
        "it": "Radio {name}.",
        "es": "Radio {name}.",
        "pt": "Radio {name}.",
        "zh": "电台 {name}。",
        "ja": "ラジオ {name}。",
    },
    "playlist_now": {
        "fr": "Lecture de {title}.",
        "en": "Now playing {title}.",
        "de": "Wiedergabe von {title}.",
        "it": "Riproduzione di {title}.",
        "es": "Reproduciendo {title}.",
        "pt": "A reproduzir {title}.",
        "zh": "正在播放 {title}。",
        "ja": "{title} を再生します。",
    },
    "playlist_now_by": {
        "fr": "Lecture de {title}, par {artist}.",
        "en": "Now playing {title} by {artist}.",
        "de": "Wiedergabe von {title} von {artist}.",
        "it": "Riproduzione di {title}, di {artist}.",
        "es": "Reproduciendo {title}, de {artist}.",
        "pt": "A reproduzir {title}, de {artist}.",
        "zh": "正在播放 {artist} 的 {title}。",
        "ja": "{artist} の {title} を再生します。",
    },
    "volume_level": {
        "fr": "Volume {percent} pour cent.",
        "en": "Volume {percent} percent.",
        "de": "Lautstaerke {percent} Prozent.",
        "it": "Volume {percent} percento.",
        "es": "Volumen {percent} por ciento.",
        "pt": "Volume {percent} por cento.",
        "zh": "音量 {percent}%。",
        "ja": "音量 {percent} パーセント。",
    },
    "playlist_empty_switch_radio": {
        "fr": "Aucun fichier MP3 detecte. Bascule en mode radio.",
        "en": "No MP3 file detected. Switching to radio mode.",
        "de": "Keine MP3-Datei erkannt. Wechsel in den Radiomodus.",
        "it": "Nessun file MP3 rilevato. Passaggio alla modalita radio.",
        "es": "No se detecto ningun archivo MP3. Cambiando al modo radio.",
        "pt": "Nenhum ficheiro MP3 detetado. A mudar para o modo radio.",
        "zh": "未检测到 MP3 文件。正在切换到电台模式。",
        "ja": "MP3 ファイルが見つかりません。ラジオモードに切り替えます。",
    },
    "radio_folder_empty_playlist": {
        "fr": "Aucun fichier radio detecte. Le mode playlist continue.",
        "en": "No radio file detected. Playlist mode continues.",
        "de": "Keine Radiodatei erkannt. Der Playlist-Modus bleibt aktiv.",
        "it": "Nessun file radio rilevato. La modalita playlist continua.",
        "es": "No se detecto ningun archivo de radio. El modo lista continua.",
        "pt": "Nenhum ficheiro de radio detetado. O modo playlist continua.",
        "zh": "未检测到电台文件。播放列表模式继续。",
        "ja": "ラジオファイルが見つかりません。プレイリストモードを続けます。",
    },
}

SUPPORTED_LANGUAGES = ("fr", "en", "de", "it", "es", "pt", "zh", "ja")
FALLBACK_LANGUAGE = "en"

_language = FALLBACK_LANGUAGE
_voice_name = ""
_tts_queue = queue.Queue()
_worker_started = False
_worker_thread = None
_lock = threading.Lock()
_shutdown_requested = False


def configure(language: str = "en", voice_name: str = "") -> None:
    global _language, _voice_name
    lang = (language or "").replace("-", "_").lower()
    _language = FALLBACK_LANGUAGE
    for code in SUPPORTED_LANGUAGES:
        if lang.startswith(code):
            _language = code
            break
    _voice_name = (voice_name or "").strip()


def get_text(key: str, **kwargs) -> str:
    values = TTS_TEXTS.get(key, {})
    template = values.get(_language) or values.get(FALLBACK_LANGUAGE, "")
    try:
        return template.format(**kwargs) if kwargs else template
    except Exception:
        return template


def _normalize_voice_name(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def _voice_lookup_keys(label: str):
    keys = set()
    normalized = _normalize_voice_name(label)
    if normalized:
        keys.add(normalized)
    if " - " in (label or ""):
        short = _normalize_voice_name(label.split(" - ", 1)[0])
        if short:
            keys.add(short)
    return keys


def _build_sapi_voice_map(voice) -> dict:
    voice_map = {}

    def _register(tokens):
        try:
            count = int(tokens.Count)
        except Exception:
            count = 0
        for idx in range(count):
            try:
                token = tokens.Item(idx)
                description = str(token.GetDescription())
            except Exception:
                continue
            for key in _voice_lookup_keys(description):
                voice_map.setdefault(key, token)

    try:
        _register(voice.GetVoices())
    except Exception:
        pass
    try:
        category = comtypes.client.CreateObject("SAPI.SpObjectTokenCategory", dynamic=True)
        category.SetId(r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices", False)
        _register(category.EnumerateTokens())
    except Exception:
        pass
    return voice_map


def _select_sapi_voice_token(voice, voice_map: dict, voice_name: str) -> None:
    key = _normalize_voice_name(voice_name)
    if not key:
        return
    token = voice_map.get(key)
    if token is None:
        for candidate_key, candidate_token in voice_map.items():
            if candidate_key == key or candidate_key.startswith(key) or key in candidate_key:
                token = candidate_token
                break
    if token is not None:
        try:
            voice.Voice = token
        except Exception:
            pass


def _speak_with_fresh_engine(text: str, voice_name: str = "") -> None:
    if not COMTYPES_OK or not text:
        return

    initialized = False
    voice = None
    try:
        comtypes.CoInitialize()
        initialized = True
        voice = comtypes.client.CreateObject("SAPI.SpVoice", dynamic=True)
        voice_map = _build_sapi_voice_map(voice)
        _select_sapi_voice_token(voice, voice_map, voice_name)
        voice.Speak(text)
    finally:
        voice = None
        if initialized:
            try:
                comtypes.CoUninitialize()
            except Exception:
                pass


def _tts_process_entry(text: str, voice_name: str) -> None:
    try:
        _speak_with_fresh_engine(text, voice_name)
    except Exception:
        pass


def _estimate_timeout(text: str) -> float:
    # Les annonces PitLane sont courtes : si un Speak() reste bloque au-dela,
    # on privilegie la reprise rapide du systeme plutot que d'attendre longtemps.
    return max(5.0, min(12.0, 1.5 + (len(text or "") / 18.0)))


def _kill_process(proc) -> None:
    if proc is None:
        return
    try:
        if proc.is_alive():
            proc.terminate()
            proc.join(1.0)
    except Exception:
        pass
    try:
        if proc.is_alive():
            proc.kill()
            proc.join(1.0)
    except Exception:
        pass
    try:
        proc.close()
    except Exception:
        pass


def _close_mp_queue(q) -> None:
    if q is None:
        return
    try:
        q.close()
    except Exception:
        pass
    try:
        q.cancel_join_thread()
    except Exception:
        pass


def _engine_process_entry(in_q, out_q) -> None:
    while True:
        try:
            item = in_q.get()
        except Exception:
            break
        if item is None:
            break

        seq, text, voice_name = item
        status = "ok"
        try:
            _speak_with_fresh_engine(text, voice_name)
        except Exception:
            status = "error"
        try:
            out_q.put((seq, status))
        except Exception:
            pass


def _start_engine(spawn_ctx):
    in_q = spawn_ctx.Queue()
    out_q = spawn_ctx.Queue()
    proc = spawn_ctx.Process(
        target=_engine_process_entry,
        args=(in_q, out_q),
        daemon=True,
        name="PitLaneTTSEngine",
    )
    proc.start()
    return proc, in_q, out_q


def _stop_engine(proc, in_q, out_q) -> None:
    try:
        if in_q is not None:
            in_q.put_nowait(None)
    except Exception:
        pass
    _kill_process(proc)
    _close_mp_queue(in_q)
    _close_mp_queue(out_q)


def _ensure_worker() -> None:
    global _worker_started, _worker_thread, _shutdown_requested
    with _lock:
        if _worker_started:
            return
        _worker_started = True
        _shutdown_requested = False

    def _worker():
        spawn_ctx = mp.get_context("spawn")
        engine_proc = None
        engine_in_q = None
        engine_out_q = None
        next_seq = 0
        while True:
            item = _tts_queue.get()
            if item is None or _shutdown_requested:
                _tts_queue.task_done()
                break

            text, voice_name, on_complete = item
            try:
                if text and COMTYPES_OK:
                    if engine_proc is None or not engine_proc.is_alive():
                        _stop_engine(engine_proc, engine_in_q, engine_out_q)
                        engine_proc, engine_in_q, engine_out_q = _start_engine(spawn_ctx)

                    next_seq += 1
                    current_seq = next_seq
                    try:
                        engine_in_q.put((current_seq, text, voice_name))
                    except Exception:
                        _stop_engine(engine_proc, engine_in_q, engine_out_q)
                        engine_proc, engine_in_q, engine_out_q = _start_engine(spawn_ctx)
                        engine_in_q.put((current_seq, text, voice_name))

                    deadline = time.monotonic() + _estimate_timeout(text)
                    done = False
                    while time.monotonic() < deadline and not _shutdown_requested:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            break
                        try:
                            result_seq, _status = engine_out_q.get(timeout=min(0.2, remaining))
                        except queue.Empty:
                            continue
                        except Exception:
                            break
                        if result_seq == current_seq:
                            done = True
                            break

                    if not done:
                        _stop_engine(engine_proc, engine_in_q, engine_out_q)
                        engine_proc, engine_in_q, engine_out_q = None, None, None
            except Exception:
                pass
            finally:
                if on_complete:
                    try:
                        on_complete()
                    except Exception:
                        pass
                _tts_queue.task_done()

        _stop_engine(engine_proc, engine_in_q, engine_out_q)

    _worker_thread = threading.Thread(target=_worker, name="TTS-Worker", daemon=True)
    _worker_thread.start()


def enqueue(text: str, on_complete=None) -> None:
    if not text or _shutdown_requested:
        return
    _ensure_worker()
    _tts_queue.put((text, _voice_name, on_complete))


def enqueue_key(key: str, on_complete=None, **kwargs) -> None:
    enqueue(get_text(key, **kwargs), on_complete=on_complete)


def shutdown() -> None:
    global _worker_started, _worker_thread, _shutdown_requested
    with _lock:
        if not _worker_started:
            return
        _worker_started = False
        _shutdown_requested = True
    try:
        while True:
            item = _tts_queue.get_nowait()
            try:
                _tts_queue.task_done()
            except Exception:
                pass
            if item is None:
                break
    except queue.Empty:
        pass
    except Exception:
        pass
    try:
        _tts_queue.put_nowait(None)
    except Exception:
        pass
    if _worker_thread is not None:
        try:
            _worker_thread.join(1.0)
        except Exception:
            pass
        _worker_thread = None


atexit.register(shutdown)
