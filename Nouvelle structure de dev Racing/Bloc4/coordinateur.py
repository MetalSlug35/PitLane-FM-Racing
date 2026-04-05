# =============================================================================
#  Bloc4 - coordinateur.py
#  Coordinateur central de PitLane FM.
#  Version TTS-only: plus de separation Flat / VR, plus de toaster.
# =============================================================================

import atexit
import threading
import time

import Bloc5.interpreteur_shortcuts as shortcuts
import Bloc6.music_player as music
import Bloc8.TTS_player as tts
import Bloc9.Stop_saver as saver
import Bloc10.Support as support


DEFAULT_POLICY = {
    "game_closed": "exit",
    "loading": "stop",
    "menus": "stop",
    "pre_race": "stop",
    "race": "play",
    "qualifying": "play",
    "practice": "play",
    "hotlap": "play",
    "hotstint": "play",
    "time_attack": "play",
    "paused": "hold",
    "setup_menu": "stop",
    "pit_lane": "play",
    "pit_stop": "play",
    "on_track": "play",
    "replay": "stop",
    "unknown": "stop",
}


class Coordinateur:
    def __init__(self, config: dict):
        self._cfg = config
        self._config_file = config.get("config_file", "")
        self._get_proc = config["get_proc"]
        self._get_state = config["get_game_state"]
        self._policy_map = {**DEFAULT_POLICY, **config.get("music_policy_map", {})}
        self._interval = float(config.get("check_interval", 0.8))
        self._donate_url = config.get("donate_url", "")
        self._nexus_url = config.get("nexus_url", "")
        self._logo_path = config.get("logo_path", "")
        self._app_title = config.get("app_title", "PitLane FM")
        self._donate_trigger = int(config.get("donation_trigger", 10))
        self._on_exit_hook = config.get("on_exit_hook")
        self._arret_demande = threading.Event()
        self._finalized = False
        self._finalize_lock = threading.Lock()

        self._state = config
        self._etat_prec = None
        self._politique_prec = None

    def _notification_enabled(self, kind: str) -> bool:
        notif = self._state.get("notification_settings", {})
        return bool(notif.get(kind, False))

    def _should_duck_radio_intro(self) -> bool:
        # Le fade radio ne sert que pour laisser passer un TTS radio.
        return self._notification_enabled("radio")

    def _enqueue_tts(self, text: str, duck_radio: bool = False, on_complete=None) -> None:
        if not text:
            return

        should_duck = bool(duck_radio and music.get_mode() == "radio")
        token = music.begin_radio_tts_duck() if should_duck else None

        def _after_tts():
            if callable(on_complete):
                try:
                    on_complete()
                except Exception:
                    pass
            if token is not None:
                music.end_radio_tts_duck(token)

        tts.enqueue(text, on_complete=_after_tts if (token is not None or callable(on_complete)) else None)

    def _init_blocs(self) -> None:
        state = self._state

        tts.configure(
            language=state.get("language", "en"),
            voice_name=state.get("tts_voice", ""),
        )

        music.configure(
            music_folders=state.get("music_folders", self._cfg.get("music_folders", [])),
            music_folder=state.get("music_folder", self._cfg.get("music_folder", "")),
            radio_folder=state.get("radio_folder", self._cfg.get("radio_folder", "")),
            on_track_started=self._on_track_started,
            on_track_ended=self._on_track_ended,
        )
        music.set_radio_intro_duck(self._should_duck_radio_intro())
        music.set_volume(state.get("volume", 0.4))
        # On recharge toujours la derniere radio connue depuis l'INI,
        # meme si l'application demarre en mode playlist. Sans cela,
        # le premier switch playlist -> radio repart sur la premiere
        # station alphabetique au lieu de reprendre la derniere radio.
        if state.get("radio_courante"):
            music.set_radio(state["radio_courante"])

        shortcuts.configure(
            raccourcis_dict=state.get("raccourcis", {}),
            actions_dict={
                "suivant": music.piste_suivante,
                "switch": self._switcher_mode,
                "volume_up_start": lambda: music.start_volume_ramp("up"),
                "volume_up_end": lambda: (music.stop_volume_ramp(), self._notifier_volume()),
                "volume_up_step": lambda: (music.adjust_volume_step("up"), self._notifier_volume()),
                "volume_down_start": lambda: music.start_volume_ramp("down"),
                "volume_down_end": lambda: (music.stop_volume_ramp(), self._notifier_volume()),
                "volume_down_step": lambda: (music.adjust_volume_step("down"), self._notifier_volume()),
            },
        )

    def _on_track_started(self, titre: str, artiste: str, mode: str, on_complete=None) -> None:
        if mode == "radio":
            if self._notification_enabled("radio"):
                self._enqueue_tts(
                    tts.get_text("radio_now", name=titre),
                    duck_radio=True,
                    on_complete=on_complete,
                )
            return

        if mode == "playlist":
            if self._notification_enabled("playlist"):
                if artiste:
                    txt = tts.get_text("playlist_now_by", title=titre, artist=artiste)
                else:
                    txt = tts.get_text("playlist_now", title=titre)
                self._enqueue_tts(txt)
            return

        if mode == "switch_to_radio" and self._notification_enabled("switch"):
            self._enqueue_tts(tts.get_text("playlist_empty_switch_radio"))

    def _on_track_ended(self) -> None:
        return

    def _switcher_mode(self) -> None:
        def _on_switch(event: str):
            if not self._notification_enabled("switch"):
                return
            if event == "switch_to_radio":
                self._enqueue_tts(tts.get_text("switch_to_radio"))
            elif event == "switch_to_playlist":
                self._enqueue_tts(tts.get_text("switch_to_playlist"))
            elif event == "radio_folder_empty":
                self._enqueue_tts(tts.get_text("radio_folder_empty_playlist"))

        music.switcher_mode(on_switch_notification=_on_switch)

    def _notifier_volume(self) -> None:
        if not self._notification_enabled("volume"):
            return
        pct = int(music.get_volume() * 100)
        self._enqueue_tts(
            tts.get_text("volume_level", percent=pct),
            duck_radio=True,
        )

    def _politique(self, etat_id: str) -> str:
        return self._policy_map.get(etat_id, "stop")

    def _sauvegarder(self) -> None:
        state = self._state
        state["volume"] = music.get_volume()
        state["mode"] = music.get_mode()
        state["radio_courante"] = music.get_radio_courante()
        saver.sauvegarder(self._config_file, state)

    def _finaliser(self) -> None:
        with self._finalize_lock:
            if self._finalized:
                return
            self._finalized = True

        music.arreter()
        tts.shutdown()
        self._sauvegarder()

        if saver.doit_afficher_popup(self._state, self._donate_trigger):
            support.afficher(
                app_title=self._app_title,
                donate_url=self._donate_url,
                nexus_url=self._nexus_url,
                language=self._state.get("language", "en"),
                logo_path=self._logo_path,
            )
            self._state["donation_popup_shown"] = True
            self._sauvegarder()

        if callable(self._on_exit_hook):
            try:
                self._on_exit_hook()
            except Exception:
                pass

    def demarrer(self) -> None:
        self._init_blocs()
        atexit.register(self._finaliser)

        def _ctrl_loop():
            while not self._arret_demande.is_set():
                shortcuts.tick()
                time.sleep(0.05)

        threading.Thread(target=_ctrl_loop, name="Shortcuts", daemon=True).start()

        try:
            while not self._arret_demande.is_set():
                proc = self._get_proc()
                if proc is None:
                    break

                etat = self._get_state(self._etat_prec)
                self._etat_prec = etat

                etat_id = etat.get("stateId", "unknown")
                politique = self._politique(etat_id)
                force_stop_music = bool(etat.get("forceStopMusic", False))

                shortcuts.autoriser(politique == "play")

                if politique == "exit":
                    break
                if force_stop_music:
                    music.arreter(fade=False)
                if politique == "play":
                    if not music.est_en_lecture() and not music._lecture_en_cours:
                        music.set_radio_intro_duck(self._should_duck_radio_intro())
                        duck_radio_intro = (
                            music.get_mode() == "radio" and self._should_duck_radio_intro()
                        )
                        music.lancer(duck_for_vr=duck_radio_intro)
                elif politique == "stop":
                    if music.est_en_lecture():
                        music.arreter(fade=True)

                self._politique_prec = politique
                music.tick()

                fin = time.monotonic() + self._interval
                while not self._arret_demande.is_set():
                    reste = fin - time.monotonic()
                    if reste <= 0:
                        break
                    time.sleep(min(0.01, max(0.001, reste)))
        except KeyboardInterrupt:
            pass
        finally:
            self._arret_demande.set()
            self._finaliser()

    def arreter(self) -> None:
        self._arret_demande.set()
