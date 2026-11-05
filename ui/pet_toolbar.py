"""A proximity-revealed palette for self-only companion controls."""
from pathlib import Path
import time

from PyQt6.QtCore import QPoint, QSize, QTimer, Qt, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QCursor, QIcon
from PyQt6.QtWidgets import QWidget, QToolButton, QGridLayout, QGraphicsOpacityEffect

ICONS = Path(__file__).resolve().parents[1] / "assets" / "icons"


class PetToolbar(QWidget):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self._revealed = False
        self._last_near = 0.0
        self._button_size = 0
        self.buttons = {}
        self._colors = {}
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        layout = QGridLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        entries = [
            ("pet", "heart", "打个招呼", "#f9d9e2", 0, 0, window._pet_interact),
            ("quiet", "moon", "安静陪伴", "#d2ede3", 0, 1, None),
            ("smaller", "minus", "缩小", "#d7e8f8", 1, 0, lambda: self._zoom(1 / 1.1)),
            ("larger", "plus", "放大", "#d7e8f8", 1, 1, lambda: self._zoom(1.1)),
            ("reset", "rotate-ccw", "恢复默认大小", "#f7ebc7", 2, 0, lambda: window._controls.request_scale(1.0)),
            ("left", "arrow-left", "靠左边", "#e5e8ee", 3, 0, lambda: window._controls.dock("left")),
            ("right", "arrow-right", "靠右边", "#e5e8ee", 3, 1, lambda: window._controls.dock("right")),
        ]
        for name, icon, tooltip, color, row, column, callback in entries:
            button = QToolButton(self)
            button.setIcon(QIcon(str(ICONS / (icon + ".svg"))))
            button.setToolTip(tooltip)
            button.setAccessibleName(tooltip)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            if callback:
                button.clicked.connect(callback)
            self.buttons[name] = button
            self._colors[name] = color
            layout.addWidget(button, row, column, 1, 2 if name == "reset" else 1, Qt.AlignmentFlag.AlignCenter)
        quiet = self.buttons["quiet"]
        quiet.setCheckable(True)
        quiet.toggled.connect(window._set_quiet)
        self.sync_quiet()
        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._effect.setOpacity(0)
        self._fade = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade.setDuration(160)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.finished.connect(self._fade_finished)
        self._poll = QTimer(self)
        self._poll.timeout.connect(self._check_pointer)
        self._poll.start(100)
        self.hide()

    def _zoom(self, factor):
        self.window._controls.zoom_by(factor, self.mapToGlobal(self.rect().center()))

    def sync_quiet(self):
        button = self.buttons["quiet"]
        button.blockSignals(True)
        button.setChecked(self.window._quiet_mode)
        button.blockSignals(False)
        button.setToolTip("安静陪伴中；点击允许主动聊天" if self.window._quiet_mode else "点击开启安静陪伴")

    def reposition(self, scale):
        size = max(28, round(32 * scale))
        if size != self._button_size:
            self._button_size = size
            self.layout().setSpacing(max(4, round(5 * scale)))
            for name, button in self.buttons.items():
                button.setFixedSize(size, size)
                button.setIconSize(QSize(round(size * 0.53), round(size * 0.53)))
                button.setStyleSheet(
                    "QToolButton {background: %s; border: 1px solid #ffffff; border-radius: %spx;}"
                    "QToolButton:hover {background: #ffffff; border: 2px solid #c9d6df;}"
                    "QToolButton:pressed {background: #c9dae8;}"
                    "QToolButton:checked {background: #a9dac5; border: 2px solid #719e8a;}"
                    % (self._colors[name], size // 2))
            self.setFixedSize(self.layout().sizeHint())
        self.move(self.window.width() - self.width() - 6,
                  max(4, min(round(14 * scale), self.window.avatar_label.height() - self.height())))
        self.raise_()

    def _check_pointer(self):
        if not self.window.isVisible() or self.window._closing:
            return
        self.update_proximity(QCursor.pos(), time.monotonic())

    def update_proximity(self, global_pos, now):
        avatar = self.window.avatar_label
        local = avatar.mapFromGlobal(global_pos)
        near = avatar.rect().adjusted(-24, -24, 24, 24).contains(local)
        near = near or self.rect().adjusted(-12, -12, 12, 12).contains(self.mapFromGlobal(global_pos))
        near = near or any(button.isDown() for button in self.buttons.values())
        if near:
            self._last_near = now
            self.reveal(True)
        elif now - self._last_near > 0.4:
            self.reveal(False)

    def reveal(self, visible):
        if visible == self._revealed:
            return
        self._revealed = visible
        self._fade.stop()
        if visible:
            self.show()
            self.raise_()
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, not visible)
        self._fade.setStartValue(self._effect.opacity())
        self._fade.setEndValue(1.0 if visible else 0.0)
        self._fade.start()

    def _fade_finished(self):
        if not self._revealed:
            self.hide()

    def shutdown(self):
        self._poll.stop()
        self._fade.stop()
        self.hide()
