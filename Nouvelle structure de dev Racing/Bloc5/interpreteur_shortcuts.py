# =============================================================================
#  Bloc5 — interpreteur_shortcuts.py
#  Gestion des raccourcis clavier / manette / souris.
#  Module universel — aucune dépendance à un jeu spécifique.
#
#  API publique :
#    configure(raccourcis_dict, actions_dict)
#      raccourcis_dict : dict issu de la section [Raccourcis] de l'INI
#      actions_dict    : {"suivant": callable, "switch": callable,
#                         "volume_up_start": callable, "volume_up_end": callable,
#                         "volume_down_start": callable, "volume_down_end": callable}
#    tick()            — à appeler à chaque itération (~50 ms)
#    autoriser(bool)   — active / désactive la réception des raccourcis
# =============================================================================

import json
import time
import ctypes
import ctypes.wintypes

import pygame
try:
    from pygame._sdl2 import controller as sdl2_controller
    SDL2_CONTROLLER_OK = True
except Exception:
    sdl2_controller = None
    SDL2_CONTROLLER_OK = False

# ─────────────────────────────────────────────────────────────────────────────
#  CONSTANTES GESTES
# ─────────────────────────────────────────────────────────────────────────────
GESTURE_PRESS            = "press"
GESTURE_HOLD             = "hold"
GESTURE_DOUBLE_TAP       = "double_tap"
GESTURE_DOUBLE_TAP_HOLD  = "double_tap_hold"

DOUBLE_TAP_WINDOW    = 0.35   # fenêtre double-tap (secondes)
HOLD_TRIGGER_DELAY   = 0.45   # délai avant déclenchement hold
AXIS_TRIGGER_THRESHOLD = 0.6  # seuil axe manette
INPUT_DEVICE_REFRESH = 1.0    # intervalle rafraîchissement manettes
MODIFIER_DELAI       = 0.15   # délai confirmation modificateur
INPUT_BINDING_VERSION = 2

# ─────────────────────────────────────────────────────────────────────────────
#  XINPUT
# ─────────────────────────────────────────────────────────────────────────────
XINPUT_BUTTON_MASKS = {
    0: 0x1000, 1: 0x2000, 2: 0x4000, 3: 0x8000,
    4: 0x0100, 5: 0x0200, 6: 0x0020, 7: 0x0010,
    8: 0x0040, 9: 0x0080, 10: 0x0001, 11: 0x0002,
    12: 0x0004, 13: 0x0008,
}
MOUSE_VK_BY_BUTTON = {1: 0x01, 2: 0x02, 3: 0x04, 4: 0x05, 5: 0x06}
MAPVK_VSC_TO_VK_EX = 3

try:
    _xinput = ctypes.windll.xinput1_4
except Exception:
    try:
        _xinput = ctypes.windll.xinput1_3
    except Exception:
        _xinput = None

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
_user32.GetAsyncKeyState.restype  = ctypes.c_short
_user32.MapVirtualKeyW.argtypes   = [ctypes.c_uint, ctypes.c_uint]
_user32.MapVirtualKeyW.restype    = ctypes.c_uint


class XINPUT_GAMEPAD(ctypes.Structure):
    _fields_ = [
        ("wButtons",      ctypes.c_ushort),
        ("bLeftTrigger",  ctypes.c_ubyte),
        ("bRightTrigger", ctypes.c_ubyte),
        ("sThumbLX",      ctypes.c_short),
        ("sThumbLY",      ctypes.c_short),
        ("sThumbRX",      ctypes.c_short),
        ("sThumbRY",      ctypes.c_short),
    ]


class XINPUT_STATE(ctypes.Structure):
    _fields_ = [
        ("dwPacketNumber", ctypes.c_ulong),
        ("Gamepad",        XINPUT_GAMEPAD),
    ]


if _xinput is not None:
    try:
        _xinput.XInputGetState.argtypes = [ctypes.c_uint, ctypes.POINTER(XINPUT_STATE)]
        _xinput.XInputGetState.restype  = ctypes.c_uint
    except Exception:
        pass


def _xinput_get_state(slot: int):
    if _xinput is None:
        return None
    state = XINPUT_STATE()
    try:
        if _xinput.XInputGetState(int(slot), ctypes.byref(state)) != 0:
            return None
    except Exception:
        return None
    return state


def _is_xinput_candidate(name: str, guid: str) -> bool:
    low_name = (name or "").lower()
    low_guid = (guid or "").lower()
    return ("xbox" in low_name) or ("xinput" in low_name) or ("5d08" in low_guid)


# ─────────────────────────────────────────────────────────────────────────────
#  PARSING BINDING
# ─────────────────────────────────────────────────────────────────────────────
def charger_raccourci(valeur: str, modifier: bool = False) -> dict | None:
    """Parse une valeur INI en dict de binding."""
    raw = (valeur or "").strip()
    if not raw or raw.lower() == "skip":
        return None

    # Nouveau format JSON
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                data.setdefault("version", INPUT_BINDING_VERSION)
                data["gesture"] = GESTURE_HOLD if modifier else data.get("gesture", GESTURE_PRESS)
                return data
        except Exception:
            pass

    parts = raw.lower().split(":")
    if len(parts) < 2:
        return None

    gesture = GESTURE_HOLD if modifier else GESTURE_PRESS

    if parts[0] == "key":
        try:
            return {
                "version": 1,
                "device_kind": "keyboard_mouse",
                "input_type": "key",
                "key": int(parts[1]),
                "gesture": gesture,
            }
        except Exception:
            return None

    if parts[0] == "joy" and len(parts) >= 4:
        try:
            legacy_id = int(parts[1])
            joy_type  = parts[2]
            if joy_type == "button":
                return {
                    "version": 1,
                    "device_kind": "legacy_joystick",
                    "legacy_joy_id": legacy_id,
                    "input_type": "joy_button",
                    "button": int(parts[3]),
                    "gesture": gesture,
                }
            if joy_type == "hat" and len(parts) >= 5:
                return {
                    "version": 1,
                    "device_kind": "legacy_joystick",
                    "legacy_joy_id": legacy_id,
                    "input_type": "joy_hat",
                    "hat": int(parts[3]),
                    "direction": parts[4],
                    "gesture": gesture,
                }
        except Exception:
            return None
    return None


def signature_physique(binding: dict | None):
    if not binding:
        return None
    return (
        binding.get("device_kind"),
        binding.get("device_name"),
        binding.get("device_guid"),
        int(binding.get("device_occurrence", 0) or 0),
        binding.get("legacy_joy_id"),
        binding.get("input_type"),
        binding.get("key"),
        binding.get("button"),
        binding.get("hat"),
        binding.get("direction"),
        binding.get("axis"),
        binding.get("sign"),
        round(float(binding.get("threshold", AXIS_TRIGGER_THRESHOLD) or AXIS_TRIGGER_THRESHOLD), 3),
    )


# ─────────────────────────────────────────────────────────────────────────────
#  ÉTAT DE GESTE PAR BINDING
# ─────────────────────────────────────────────────────────────────────────────
class _EtatGeste:
    def __init__(self, enabled_gestures=None):
        self.enabled_gestures = set(enabled_gestures or [])
        self.down           = False
        self.press_since    = 0.0
        self.waiting_second = False
        self.last_release   = 0.0
        self.second_tap     = False
        self.hold_started   = False

    def synchroniser(self, down: bool, now: float):
        self.down           = down
        self.press_since    = now if down else 0.0
        self.waiting_second = False
        self.last_release   = 0.0
        self.second_tap     = False
        self.hold_started   = False

    def mettre_a_jour(self, down: bool, now: float) -> list:
        events     = []
        want_press = GESTURE_PRESS in self.enabled_gestures
        want_double = (
            GESTURE_DOUBLE_TAP in self.enabled_gestures
            or GESTURE_DOUBLE_TAP_HOLD in self.enabled_gestures
        )

        if down and not self.down:
            if self.waiting_second and (now - self.last_release) <= DOUBLE_TAP_WINDOW:
                self.second_tap     = True
                self.waiting_second = False
            else:
                if self.waiting_second and (now - self.last_release) > DOUBLE_TAP_WINDOW:
                    if want_press:
                        events.append((GESTURE_PRESS, "fire"))
                    self.waiting_second = False
                self.second_tap = False
            self.down        = True
            self.press_since = now
            self.hold_started = False

        elif not down and self.down:
            self.down = False
            if self.second_tap:
                if self.hold_started:
                    events.append((GESTURE_DOUBLE_TAP_HOLD, "end"))
                else:
                    events.append((GESTURE_DOUBLE_TAP, "fire"))
                self.second_tap   = False
                self.hold_started = False
                self.waiting_second = False
            else:
                if self.hold_started:
                    events.append((GESTURE_HOLD, "end"))
                    self.hold_started = False
                else:
                    if want_double:
                        self.waiting_second = True
                        self.last_release   = now
                    elif want_press:
                        events.append((GESTURE_PRESS, "fire"))

        if self.down and not self.hold_started and (now - self.press_since) >= HOLD_TRIGGER_DELAY:
            self.hold_started = True
            if self.second_tap:
                self.waiting_second = False
                events.append((GESTURE_DOUBLE_TAP_HOLD, "start"))
            else:
                events.append((GESTURE_HOLD, "start"))

        if (not self.down) and self.waiting_second and (now - self.last_release) > DOUBLE_TAP_WINDOW:
            self.waiting_second = False
            if want_press:
                events.append((GESTURE_PRESS, "fire"))

        return events


# ─────────────────────────────────────────────────────────────────────────────
#  GESTIONNAIRE RACCOURCIS
# ─────────────────────────────────────────────────────────────────────────────
class GestionnaireRaccourcis:
    """
    Gère les raccourcis clavier/manette.

    raccourcis_dict : dict [Raccourcis] de l'INI
      clés reconnues : "modifier", "suivant", "volume_up", "volume_down", "switch"

    actions_dict : dict d'actions callable
      clés : "suivant", "switch",
             "volume_up_start", "volume_up_end",
             "volume_down_start", "volume_down_end"
    """

    def __init__(self, raccourcis_dict: dict, actions_dict: dict):
        self._actions_cb = actions_dict or {}
        self._modificateur = charger_raccourci(raccourcis_dict.get("modifier", ""), modifier=True)

        self._binding_par_sig = {}
        self._actions_par_sig = {}
        self._gestures_par_sig = {}
        self._etats = {}
        self._joysticks = []
        self._controllers = {}
        self._dernier_refresh = 0.0
        self._mod_actif  = False
        self._mod_since  = None
        self._autorise   = True

        for action in ("suivant", "volume_up", "volume_down", "switch"):
            binding = charger_raccourci(raccourcis_dict.get(action, ""))
            if not binding:
                continue
            sig = signature_physique(binding)
            self._binding_par_sig.setdefault(sig, binding)
            self._actions_par_sig.setdefault(sig, []).append(
                (action, binding.get("gesture", GESTURE_PRESS))
            )
            self._gestures_par_sig.setdefault(sig, set()).add(
                binding.get("gesture", GESTURE_PRESS)
            )

        for sig in self._binding_par_sig:
            self._etats.setdefault(
                sig,
                _EtatGeste(self._gestures_par_sig.get(sig, set())),
            )

        self._rafraichir_joysticks(force=True)

    def autoriser(self, etat: bool) -> None:
        self._autorise = etat

    # ── Manettes ──────────────────────────────────────────────────────────────
    def _guid(self, js) -> str:
        try:
            return js.get_guid() or ""
        except Exception:
            return ""

    def _rafraichir_joysticks(self, force: bool = False) -> None:
        now = time.time()
        if not force and (now - self._dernier_refresh) < INPUT_DEVICE_REFRESH:
            return
        self._dernier_refresh = now
        try:
            pygame.joystick.init()
            if SDL2_CONTROLLER_OK:
                try:
                    sdl2_controller.init()
                except Exception:
                    pass
        except Exception:
            self._joysticks = []
            return

        occurrences = {}
        joysticks   = []
        controller_keys = set()
        xinput_slots = []
        for slot in range(4):
            if _xinput_get_state(slot) is not None:
                xinput_slots.append(slot)
        next_xinput = 0

        for idx in range(pygame.joystick.get_count()):
            try:
                js = pygame.joystick.Joystick(idx)
                js.init()
                name = js.get_name() or f"Joystick {idx + 1}"
                guid = self._guid(js)
                cle  = (name, guid)
                occ  = occurrences.get(cle, 0)
                occurrences[cle] = occ + 1
                ctrl_idx = None
                if SDL2_CONTROLLER_OK:
                    try:
                        if sdl2_controller.is_controller(idx):
                            ctrl_idx = idx
                    except Exception:
                        pass
                if ctrl_idx is not None:
                    controller_keys.add((name, guid, occ))
                xinput_slot = None
                if next_xinput < len(xinput_slots) and _is_xinput_candidate(name, guid):
                    xinput_slot = xinput_slots[next_xinput]
                    next_xinput += 1
                joysticks.append({
                    "index": idx, "joystick": js,
                    "name": name, "guid": guid,
                    "occurrence": occ,
                    "controller_index": ctrl_idx,
                    "xinput_slot": xinput_slot,
                })
            except Exception:
                pass

        self._joysticks = joysticks
        self._controllers = {k: v for k, v in self._controllers.items() if k in controller_keys}

    def _trouver_joystick(self, binding):
        if not binding:
            return None
        if binding.get("device_kind") == "legacy_joystick":
            try:
                idx = int(binding.get("legacy_joy_id", -1))
                if 0 <= idx < pygame.joystick.get_count():
                    js = pygame.joystick.Joystick(idx)
                    js.init()
                    return js
            except Exception:
                pass
            return None
        if binding.get("device_kind") != "joystick":
            return None
        name = binding.get("device_name")
        guid = binding.get("device_guid", "")
        occ  = int(binding.get("device_occurrence", 0) or 0)
        matches = [i for i in self._joysticks if i["name"] == name and i["guid"] == guid]
        return matches[min(occ, len(matches) - 1)]["joystick"] if matches else None

    def _trouver_controller(self, binding):
        if not binding or binding.get("device_kind") != "joystick" or not SDL2_CONTROLLER_OK:
            return None
        name = binding.get("device_name")
        guid = binding.get("device_guid", "")
        occ  = int(binding.get("device_occurrence", 0) or 0)
        matches = [i for i in self._joysticks if i["name"] == name and i["guid"] == guid]
        if not matches:
            return None
        item = matches[min(occ, len(matches) - 1)]
        ctrl_idx = item.get("controller_index")
        if ctrl_idx is None:
            return None
        cache_key = (item["name"], item["guid"], item["occurrence"])
        ctl = self._controllers.get(cache_key)
        try:
            if ctl is not None and ctl.attached():
                return ctl
        except Exception:
            pass
        try:
            sdl2_controller.init()
            ctl = sdl2_controller.Controller(int(ctrl_idx))
            self._controllers[cache_key] = ctl
            return ctl
        except Exception:
            self._controllers.pop(cache_key, None)
            return None

    def _trouver_xinput_slot(self, binding):
        if not binding or binding.get("device_kind") != "joystick":
            return None
        name = binding.get("device_name")
        guid = binding.get("device_guid", "")
        occ  = int(binding.get("device_occurrence", 0) or 0)
        matches = [i for i in self._joysticks if i["name"] == name and i["guid"] == guid]
        if not matches:
            return None
        return matches[min(occ, len(matches) - 1)].get("xinput_slot")

    # ── État physique ──────────────────────────────────────────────────────────
    def _etat_physique(self, binding) -> bool:
        if not binding:
            return False
        input_type = binding.get("input_type")
        try:
            if input_type == "key":
                vk = int(binding.get("vk", 0) or 0)
                if not vk:
                    sc = int(binding.get("scancode", 0) or 0)
                    if sc:
                        vk = int(_user32.MapVirtualKeyW(sc, MAPVK_VSC_TO_VK_EX) or 0)
                if vk:
                    return bool(_user32.GetAsyncKeyState(vk) & 0x8000)
                touches = pygame.key.get_pressed()
                key = int(binding.get("key", -1))
                return 0 <= key < len(touches) and bool(touches[key])

            if input_type == "mouse_button":
                vk = MOUSE_VK_BY_BUTTON.get(int(binding.get("button", 0) or 0))
                if vk:
                    return bool(_user32.GetAsyncKeyState(vk) & 0x8000)
                boutons = pygame.mouse.get_pressed(5)
                idx = int(binding.get("button", 0)) - 1
                return 0 <= idx < len(boutons) and bool(boutons[idx])

            if input_type in ("joy_button", "controller_button"):
                button = int(binding.get("button", 0))
                js = self._trouver_joystick(binding)
                if js is not None:
                    try:
                        if bool(js.get_button(button)):
                            return True
                    except Exception:
                        pass
                ctl = self._trouver_controller(binding)
                if ctl is not None:
                    try:
                        if bool(ctl.get_button(button)):
                            return True
                    except Exception:
                        pass
                mask = XINPUT_BUTTON_MASKS.get(button)
                slot = self._trouver_xinput_slot(binding)
                if mask is not None and slot is not None:
                    state = _xinput_get_state(slot)
                    if state is not None and (state.Gamepad.wButtons & mask):
                        return True
                return False

            if input_type == "controller_axis":
                ctl = self._trouver_controller(binding)
                if ctl is None:
                    return False
                valeur = int(ctl.get_axis(int(binding.get("axis", 0))))
                seuil  = int(float(binding.get("threshold", AXIS_TRIGGER_THRESHOLD) or AXIS_TRIGGER_THRESHOLD) * 32767)
                if binding.get("sign") == "negative":
                    return valeur <= -seuil
                return valeur >= seuil

            js = self._trouver_joystick(binding)
            if js is None:
                return False

            if input_type == "joy_hat":
                dm = {"up": (0, 1), "down": (0, -1), "left": (-1, 0), "right": (1, 0)}
                return js.get_hat(int(binding.get("hat", 0))) == dm.get(binding.get("direction"), (0, 0))

            if input_type == "joy_axis":
                valeur = float(js.get_axis(int(binding.get("axis", 0))))
                seuil  = float(binding.get("threshold", AXIS_TRIGGER_THRESHOLD) or AXIS_TRIGGER_THRESHOLD)
                if binding.get("sign") == "negative":
                    return valeur <= -seuil
                return valeur >= seuil
        except Exception:
            pass
        return False

    # ── Modificateur ──────────────────────────────────────────────────────────
    def _suspendre_actions(self) -> None:
        now = time.time()
        for sig, binding in self._binding_par_sig.items():
            self._etats[sig].synchroniser(self._etat_physique(binding), now)

    def _modificateur_actif(self, now: float) -> bool:
        if not self._modificateur:
            return True
        down = self._etat_physique(self._modificateur)
        if not down:
            self._mod_since = None
            self._mod_actif = False
            return False
        if self._mod_since is None:
            self._mod_since = now
        if not self._mod_actif and (now - self._mod_since) >= MODIFIER_DELAI:
            self._mod_actif = True
        return self._mod_actif

    # ── Exécution actions ─────────────────────────────────────────────────────
    def _executer(self, action: str, gesture: str, phase: str) -> None:
        cb = self._actions_cb

        if action == "suivant" and phase in ("fire", "start"):
            if "suivant" in cb:
                cb["suivant"]()

        elif action == "switch" and phase in ("fire", "start"):
            if "switch" in cb:
                cb["switch"]()

        elif action == "volume_up":
            if gesture in (GESTURE_HOLD, GESTURE_DOUBLE_TAP_HOLD):
                if phase == "start" and "volume_up_start" in cb:
                    cb["volume_up_start"]()
                elif phase == "end" and "volume_up_end" in cb:
                    cb["volume_up_end"]()
            elif phase == "fire" and "volume_up_step" in cb:
                cb["volume_up_step"]()

        elif action == "volume_down":
            if gesture in (GESTURE_HOLD, GESTURE_DOUBLE_TAP_HOLD):
                if phase == "start" and "volume_down_start" in cb:
                    cb["volume_down_start"]()
                elif phase == "end" and "volume_down_end" in cb:
                    cb["volume_down_end"]()
            elif phase == "fire" and "volume_down_step" in cb:
                cb["volume_down_step"]()

    # ── Tick principal ────────────────────────────────────────────────────────
    def tick(self) -> None:
        if not self._binding_par_sig and not self._modificateur:
            return
        try:
            pygame.event.pump()
        except Exception:
            return
        self._rafraichir_joysticks()
        now = time.time()
        if not self._autorise:
            self._mod_since = None
            self._mod_actif = False
            self._suspendre_actions()
            return
        if not self._modificateur_actif(now):
            self._suspendre_actions()
            return
        for sig, binding in self._binding_par_sig.items():
            events = self._etats[sig].mettre_a_jour(self._etat_physique(binding), now)
            for action, gesture in self._actions_par_sig.get(sig, []):
                for detected, phase in events:
                    if detected == gesture:
                        self._executer(action, detected, phase)


# ─────────────────────────────────────────────────────────────────────────────
#  ÉTAT GLOBAL MODULE (instance unique)
# ─────────────────────────────────────────────────────────────────────────────
_gestionnaire: GestionnaireRaccourcis | None = None


def configure(raccourcis_dict: dict, actions_dict: dict) -> None:
    """Crée ou recrée le gestionnaire de raccourcis."""
    global _gestionnaire
    _gestionnaire = GestionnaireRaccourcis(raccourcis_dict, actions_dict)


def autoriser(etat: bool) -> None:
    if _gestionnaire is not None:
        _gestionnaire.autoriser(etat)


def tick() -> None:
    if _gestionnaire is not None:
        _gestionnaire.tick()
