"""Window-local zoom and placement. No global hooks or external desktop control."""
import math
import time
from PyQt6.QtCore import QObject, QEvent, QPoint, QTimer, Qt
from PyQt6.QtGui import QFont, QKeySequence, QShortcut
from PyQt6.QtWidgets import QApplication, QWidget


class WindowControls(QObject):
    MIN_SCALE = 0.7
    MAX_SCALE = 1.75

    def __init__(self, window, preferences):
        super().__init__(window)
        self.window, self.preferences = window, preferences
        self.scale = self._target_scale = 1.0
        self._base_size = window.size()
        self._base_avatar = window.avatar_label.size()
        self._bubble_min, self._bubble_max = window.bubble.extents
        self._status_font = QFont(window.status_label.font())
        self._pinch_start = 1.0
        self._anchor = None
        self._last_frame = 0.0
        self._apply_timer = QTimer(self)
        self._apply_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._apply_timer.timeout.connect(self._apply_pending)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self.save)
        for widget in [window, *window.findChildren(QWidget)]:
            widget.installEventFilter(self)
            widget.grabGesture(Qt.GestureType.PinchGesture)
        window.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents)
        window.avatar_label.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents)
        self._shortcuts = []
        for key, callback in (("Ctrl+=", lambda: self.zoom_by(1.1)),
                              ("Ctrl+-", lambda: self.zoom_by(1 / 1.1)),
                              ("Ctrl+0", lambda: self.request_scale(1.0))):
            shortcut = QShortcut(QKeySequence(key), window)
            shortcut.activated.connect(callback)
            self._shortcuts.append(shortcut)
        if preferences.position:
            window.move(*preferences.position)
        self.set_scale(preferences.scale)
        self.clamp_position()

    def screen_rect(self, point=None):
        point = point if point is not None else self.window.frameGeometry().center()
        screen = QApplication.screenAt(point) or QApplication.primaryScreen()
        return screen.availableGeometry()

    def set_scale(self, scale, anchor=None):
        """Immediate sizing for initialization, display changes and tests."""
        if not math.isfinite(scale) or scale <= 0:
            return
        self._apply_timer.stop()
        self._target_scale = self._bounded_scale(scale, anchor)
        self._render_scale(self._target_scale, anchor)
        self.window._sentence_player.reflow()
        self.changed()

    def _bounded_scale(self, scale, anchor=None):
        screen = self.screen_rect(anchor)
        upper = min(self.MAX_SCALE, (screen.width() - 16) / self._base_size.width(),
                    (screen.height() - 16) / self._base_size.height())
        return max(min(self.MIN_SCALE, upper), min(upper, scale))

    def _render_scale(self, scale, anchor=None):
        window = self.window
        screen = self.screen_rect(anchor)
        old = window.geometry()
        anchor = anchor if anchor is not None else old.bottomRight() + QPoint(1, 1)
        rx, ry = (anchor.x() - old.x()) / old.width(), (anchor.y() - old.y()) / old.height()
        self.scale = scale
        width, height = round(self._base_size.width() * scale), round(self._base_size.height() * scale)
        window.setFixedSize(width, height)
        window.avatar_mgr.set_size((round(self._base_avatar.width() * scale), round(self._base_avatar.height() * scale)))
        window._bottom_layout.setContentsMargins(round(12 * scale), 0, round(12 * scale), round(12 * scale))
        window._bottom_layout.setSpacing(round(6 * scale))
        window.input_bar.apply_scale(scale)
        font = QFont(self._status_font)
        font.setPointSizeF(max(1, self._status_font.pointSizeF() * scale))
        window.status_label.setFont(font)
        window.status_label.setMaximumHeight(round(60 * scale))
        window.bubble.apply_scale(scale,
            tuple(round(n * scale) for n in self._bubble_min),
            tuple(round(n * scale) for n in self._bubble_max))
        window.layout().activate()
        window.move(round(anchor.x() - rx * width), round(anchor.y() - ry * height))
        self.clamp_position(screen)
        toolbar = getattr(window, "_pet_toolbar", None)
        if toolbar:
            toolbar.reposition(scale)
        window._sync_observation_rect()

    def request_scale(self, scale, anchor=None):
        if not math.isfinite(scale) or scale <= 0:
            return
        self._target_scale = self._bounded_scale(scale, anchor)
        if not self._apply_timer.isActive():
            self._anchor = anchor
            self._last_frame = time.perf_counter()
            self._apply_timer.start(16)

    def zoom_by(self, factor, anchor=None):
        if not math.isfinite(factor) or factor <= 0:
            return
        self.request_scale(self._target_scale * factor, anchor)

    def _apply_pending(self):
        now = time.perf_counter()
        elapsed = max(0.001, min(0.05, now - self._last_frame))
        self._last_frame = now
        # Follow the continuously updated target, not individual wheel notches.
        next_scale = self.scale + (self._target_scale - self.scale) * (1 - math.exp(-elapsed / 0.045))
        settled = abs(next_scale - self._target_scale) * self._base_size.height() < 0.5
        self._render_scale(self._target_scale if settled else next_scale, self._anchor)
        if settled:
            self._apply_timer.stop()
            self.window._sentence_player.reflow()
            self.changed()

    def clamp_position(self, screen=None):
        window = self.window
        screen = screen if screen is not None else self.screen_rect()
        x = max(screen.left(), min(window.x(), screen.right() + 1 - window.width()))
        y = max(screen.top(), min(window.y(), screen.bottom() + 1 - window.height()))
        window.move(x, y)

    def dock(self, side):
        screen = self.screen_rect()
        x = screen.left() + 12 if side == "left" else screen.right() + 1 - self.window.width() - 12
        self.window.move(x, screen.bottom() + 1 - self.window.height() - 12)
        self.clamp_position(screen)
        self.window._sync_observation_rect()
        self.changed()

    def changed(self):
        self._save_timer.start(400)

    def save(self):
        self.preferences.scale = self.scale
        self.preferences.quiet = self.window._quiet_mode
        self.preferences.position = [self.window.x(), self.window.y()]
        self.preferences.save()

    def close(self):
        self._apply_timer.stop()
        self._save_timer.stop()
        for widget in [self.window, *self.window.findChildren(QWidget)]:
            widget.removeEventFilter(self)
        self.save()

    def handle_pinch(self, gesture):
        state = gesture.state()
        if state == Qt.GestureState.GestureStarted:
            self._pinch_start = self._target_scale
        if state == Qt.GestureState.GestureCanceled:
            self.set_scale(self._pinch_start)
            return
        factor = gesture.totalScaleFactor()
        if math.isfinite(factor) and factor > 0:
            anchor = gesture.hotSpot().toPoint() if gesture.hasHotSpot() else None
            self.request_scale(self._pinch_start * factor, anchor)

    def eventFilter(self, watched, event):
        # Qt can still dispatch destruction events while Python clears cycles.
        window = getattr(self, "window", None)
        if window is None or getattr(window, "_closing", True):
            return False
        if event.type() == QEvent.Type.Wheel:
            local = self.window.avatar_label.mapFromGlobal(event.globalPosition().toPoint())
            over_avatar = self.window.avatar_label.rect().contains(local)
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier or over_avatar:
                pixels = event.pixelDelta().y()
                delta = pixels or event.angleDelta().y()
                if delta:
                    steps = max(-4, min(4, delta / (60 if pixels else 120)))
                    self.zoom_by(1.1 ** steps, event.globalPosition().toPoint())
                    event.accept()
                    return True
        elif event.type() == QEvent.Type.Gesture:
            pinch = event.gesture(Qt.GestureType.PinchGesture)
            if pinch is not None:
                self.handle_pinch(pinch)
                event.accept(pinch)
                return True
        elif event.type() == QEvent.Type.NativeGesture:
            if event.gestureType() == Qt.NativeGestureType.ZoomNativeGesture:
                self.zoom_by(1 + event.value(), event.globalPosition().toPoint())
                event.accept()
                return True
        elif event.type() == QEvent.Type.MouseButtonDblClick and watched is self.window.avatar_label:
            if event.button() == Qt.MouseButton.LeftButton:
                self.window._pet_interact()
                event.accept()
                return True
        return False
