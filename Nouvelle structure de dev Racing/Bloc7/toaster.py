"""
Persistent flat-screen notification overlay using PyQt6.

Public API:
    configure(app_id, app_name, icon_path, accent_color)
    notify(ligne1, ligne2="", tag="")
    notify_track(track_path, tag="")
    pump()

Design goals:
    - One notification system only
    - No Windows toast host
    - No PowerShell / no VBS / no tkinter
    - Keep rendering path alive between notifications
    - Never steal focus
    - Run Qt on the main thread, pumped by the main loop
"""

from __future__ import annotations

import os
import queue
import time
from pathlib import Path

try:
    from mutagen import File as _mutagen_file
except Exception:
    _mutagen_file = None

try:
    from mutagen.id3 import ID3 as _MutagenID3
except Exception:
    _MutagenID3 = None

try:
    from PyQt6.QtCore import Qt, QTimer, QRect, QSize
    from PyQt6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPainterPath, QPen
    from PyQt6.QtWidgets import QApplication, QWidget
    _PYQT_OK = True
except Exception:
    Qt = None
    QTimer = None
    QRect = None
    QSize = None
    QColor = None
    QFont = None
    QGuiApplication = None
    QPainter = None
    QPainterPath = None
    QPen = None
    QApplication = None
    QWidget = None
    _PYQT_OK = False


_TOAST_WIDTH = 420
_TOAST_HEIGHT_ONE_LINE = 84
_TOAST_HEIGHT_TWO_LINES = 108
_TOAST_MARGIN_RIGHT = 24
_TOAST_MARGIN_BOTTOM = 24
_TOAST_DURATION_MS = 2200
_DEDUP_WINDOW_SECONDS = 0.35

_app_id = "PitLaneFM"
_app_name = "PitLane FM"
_icon_path = ""
_accent_color = "#d02929"

_toast_queue: "queue.Queue[tuple[str, str, str] | None]" = queue.Queue()
_toast_counter = 0
_last_sent_by_tag: dict[str, tuple[float, str, str]] = {}
_runtime = None


def _clean_tag_value(value: object) -> str:
    if isinstance(value, (list, tuple)):
        for item in value:
            cleaned = _clean_tag_value(item)
            if cleaned:
                return cleaned
        return ""
    return str(value or "").strip()


def _looks_like_mp3_path(value: object) -> bool:
    if not isinstance(value, (str, os.PathLike)):
        return False
    try:
        path = Path(value)
    except Exception:
        return False
    return path.suffix.lower() == ".mp3" and path.exists() and path.is_file()


def _read_mp3_display(path_value: object) -> tuple[str, str]:
    try:
        path = Path(path_value)
    except Exception:
        return "", ""

    fallback = path.stem.replace("_", " ").strip()
    if _MutagenID3 is not None:
        try:
            tags = _MutagenID3(str(path))
            artist = _clean_tag_value(getattr(tags.get("TPE1"), "text", ""))
            title = _clean_tag_value(getattr(tags.get("TIT2"), "text", ""))
            if artist and title:
                return artist, title
            if title:
                return title, ""
            if artist:
                return artist, fallback if fallback and fallback.lower() != artist.lower() else ""
        except Exception:
            pass

    if _mutagen_file is not None:
        try:
            audio = _mutagen_file(str(path), easy=True)
            tags = getattr(audio, "tags", None) or {}
            artist = _clean_tag_value(tags.get("artist"))
            title = _clean_tag_value(tags.get("title"))
            if artist and title:
                return artist, title
            if title:
                return title, ""
            if artist:
                return artist, fallback if fallback and fallback.lower() != artist.lower() else ""
        except Exception:
            pass

    return fallback, ""


def _resolve_display_lines(ligne1: str, ligne2: str) -> tuple[str, str]:
    for candidate in (ligne2, ligne1):
        if _looks_like_mp3_path(candidate):
            return _read_mp3_display(candidate)
    return ligne1 or "", ligne2 or ""


def _resolve_toast_title(tag: str, ligne1: str, ligne2: str) -> str:
    app = (_app_name or "PitLane FM").upper()
    lowered_tag = (tag or "").strip().lower()
    lowered_l1 = (ligne1 or "").strip().lower()
    if "radio" in lowered_tag or "mode radio" in lowered_l1:
        return f"{app} RADIO"
    if "playlist" in lowered_tag or "playlist" in lowered_l1:
        return f"{app} PLAYLIST"
    if _looks_like_mp3_path(ligne1) or _looks_like_mp3_path(ligne2):
        return f"{app} PLAYLIST"
    return app


class _OverlayWidget(QWidget):
    def __init__(self):
        super().__init__(None)
        self._title = ""
        self._line1 = ""
        self._line2 = ""
        self._height = _TOAST_HEIGHT_ONE_LINE
        self._accent_color = _accent_color

        flags = (
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        if hasattr(Qt.WindowType, "WindowTransparentForInput"):
            flags |= Qt.WindowType.WindowTransparentForInput
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._park)

        self._park()
        self.show()

    def _work_geometry(self):
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return QRect(0, 0, 1920, 1080)
        return screen.availableGeometry()

    def _park(self):
        work = self._work_geometry()
        self.setWindowOpacity(0.01)
        self.setFixedSize(QSize(1, 1))
        self.move(max(work.left(), work.right() - 2), max(work.top(), work.bottom() - 2))
        self.update()

    def show_payload(self, ligne1: str, ligne2: str, tag: str):
        ligne1, ligne2 = _resolve_display_lines(ligne1 or "", ligne2 or "")
        if not ligne1 and not ligne2:
            return
        self._title = _resolve_toast_title(tag, ligne1, ligne2)
        self._line1 = ligne1
        self._line2 = ligne2 or ""
        self._height = _TOAST_HEIGHT_TWO_LINES if self._line2 else _TOAST_HEIGHT_ONE_LINE
        self._accent_color = _accent_color

        work = self._work_geometry()
        x = int(work.right() - _TOAST_WIDTH - _TOAST_MARGIN_RIGHT)
        y = int(work.bottom() - self._height - _TOAST_MARGIN_BOTTOM)
        self.setFixedSize(QSize(_TOAST_WIDTH, self._height))
        self.move(x, y)
        self.setWindowOpacity(1.0)
        self.show()
        self.update()
        self._hide_timer.start(_TOAST_DURATION_MS)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        rect = self.rect()
        path = QPainterPath()
        path.addRoundedRect(float(rect.x()), float(rect.y()), float(rect.width()), float(rect.height()), 10.0, 10.0)

        painter.fillPath(path, QColor(23, 22, 18, 245))
        painter.fillRect(0, 0, 6, rect.height(), QColor(self._accent_color))

        pen = QPen(QColor(58, 58, 58, 220))
        pen.setWidth(1)
        painter.setPen(pen)
        painter.drawPath(path)

        title_font = QFont("Segoe UI", 10)
        title_font.setWeight(QFont.Weight.DemiBold)
        body_font = QFont("Segoe UI", 10)

        painter.setPen(QColor(229, 229, 229))
        painter.setFont(title_font)
        painter.drawText(QRect(18, 10, rect.width() - 36, 22), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), self._title)

        painter.setPen(QColor(255, 255, 255))
        painter.setFont(body_font)
        painter.drawText(QRect(18, 34, rect.width() - 36, 22), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), self._line1)

        if self._line2:
            painter.setPen(QColor(208, 208, 208))
            painter.drawText(QRect(18, 58, rect.width() - 36, 20), int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), self._line2)


class _OverlayRuntime:
    def __init__(self):
        self.app = QApplication.instance() or QApplication([])
        self.widget = _OverlayWidget()

    def pump(self):
        latest = None
        while True:
            try:
                latest = _toast_queue.get_nowait()
                _toast_queue.task_done()
            except queue.Empty:
                break
        if latest:
            ligne1, ligne2, tag = latest
            self.widget.show_payload(ligne1, ligne2, tag)
        self.app.processEvents()


def _ensure_runtime():
    global _runtime
    if not _PYQT_OK:
        return None
    if _runtime is None:
        _runtime = _OverlayRuntime()
    return _runtime


def configure(
    app_id: str = "PitLaneFM",
    app_name: str = "PitLane FM",
    icon_path: str = "",
    accent_color: str = "#d02929",
) -> None:
    global _app_id, _app_name, _icon_path, _accent_color
    _app_id = app_id or "PitLaneFM"
    _app_name = app_name or "PitLane FM"
    _icon_path = icon_path or ""
    _accent_color = accent_color or "#d02929"
    _ensure_runtime()
    pump()


def notify(ligne1: str, ligne2: str = "", tag: str = "") -> None:
    global _toast_counter
    payload_l1 = ligne1 or ""
    payload_l2 = ligne2 or ""
    now = time.monotonic()
    toast_tag = (tag or "").strip()
    if toast_tag:
        last = _last_sent_by_tag.get(toast_tag)
        if last is not None:
            last_ts, last_l1, last_l2 = last
            if (now - last_ts) < _DEDUP_WINDOW_SECONDS and last_l1 == payload_l1 and last_l2 == payload_l2:
                return
        _last_sent_by_tag[toast_tag] = (now, payload_l1, payload_l2)
        unique_tag = toast_tag
    else:
        _toast_counter += 1
        unique_tag = str(_toast_counter)

    if _ensure_runtime() is None:
        return
    _toast_queue.put((payload_l1, payload_l2, unique_tag))


def notify_track(track_path: str, tag: str = "") -> None:
    ligne1, ligne2 = _read_mp3_display(track_path)
    notify(ligne1, ligne2, tag=tag or "playlist")


def pump() -> None:
    runtime = _ensure_runtime()
    if runtime is None:
        return
    runtime.pump()
