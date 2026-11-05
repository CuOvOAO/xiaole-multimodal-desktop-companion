"""Companion UI widgets; no model, capture or background initialization."""
from PyQt6.QtWidgets import QWidget, QLabel, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QSizePolicy, QStyle
from PyQt6.QtCore import Qt, pyqtSignal, QPointF, QTextBoundaryFinder
from PyQt6.QtGui import QFont, QColor, QPainter, QPen, QPolygonF, QTextLayout, QTextOption
import math
import re

# ── 明日方舟风格气泡 ──────────────────────────────────────
class AKBubble(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._width_limit = 420
        self._height_limit = 180
        self._minimum_width = 160
        self._minimum_height = 64
        self._measure_cache = {}
        self._sizing_text = ""
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)

        self.label = QLabel()
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.label.setWordWrap(True)
        self.label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.label.setFont(QFont("Microsoft YaHei UI", 10))
        self._base_font = QFont(self.label.font())
        self.label.setStyleSheet("color: #e8e4d8; background: transparent;")
        self.label.setMinimumSize(0, 0)
        self.label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        layout.addWidget(self.label)

    def set_width_limit(self, width):
        self._width_limit = max(80, width)
        self.setText(self.label.text())

    @property
    def extents(self):
        return (self._minimum_width, self._minimum_height), (self._width_limit, self._height_limit)

    def set_minimum_extent(self, width=160, height=64):
        self._minimum_width = max(80, width)
        self._minimum_height = max(40, height)
        self.setText(self.label.text())

    def set_maximum_extent(self, width, height):
        self._width_limit = max(80, width)
        self._height_limit = max(self._minimum_height, height)
        self.setText(self.label.text())

    def set_height_limit(self, height):
        self.set_maximum_extent(self._width_limit, height)

    def apply_scale(self, scale, minimum, maximum):
        text, sizing = self.label.text(), self._sizing_text
        font = QFont(self._base_font)
        font.setPointSizeF(self._base_font.pointSizeF() * scale)
        self.label.setFont(font)
        self.layout().setContentsMargins(round(14 * scale), round(12 * scale),
                                          round(14 * scale), round(12 * scale))
        self._minimum_width, self._minimum_height = minimum
        self._width_limit, self._height_limit = maximum
        self._measure_cache.clear()
        self.setText(text, sizing_text=sizing)

    def measured_size(self, text):
        """Use the same font and wrapping for page planning and visible layout."""
        key = (text, self.label.font().toString(), self._width_limit,
               self._minimum_width, self._minimum_height)
        if key in self._measure_cache:
            return self._measure_cache[key]
        margins = self.layout().contentsMargins()
        horizontal = margins.left() + margins.right()
        vertical = margins.top() + margins.bottom()
        metrics = self.label.fontMetrics()
        natural = max((metrics.horizontalAdvance(line) for line in text.split("\n")), default=0) + 4
        width = min(self._width_limit, max(self._minimum_width, natural + horizontal))
        content_width = max(1, width - horizontal - 4)
        height = 0
        for paragraph in text.split("\n"):
            layout = QTextLayout(paragraph or " ", self.label.font())
            option = QTextOption()
            option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
            layout.setTextOption(option)
            layout.beginLayout()
            while True:
                line = layout.createLine()
                if not line.isValid():
                    break
                line.setLineWidth(content_width)
                line.setLeadingIncluded(True)
                height += math.ceil(line.height())
            layout.endLayout()
        size = width, max(self._minimum_height, max(metrics.height(), height) + vertical + 2)
        if len(self._measure_cache) >= 128:
            self._measure_cache.clear()
        self._measure_cache[key] = size
        return size

    def fits_text(self, text):
        return self.measured_size(text)[1] <= self._height_limit

    def take_page(self, text):
        """Split by rendered capacity, preferring nearby sentence/word boundaries."""
        if self.fits_text(text):
            return text, ""
        low, high = 0, len(text)
        while low < high:
            mid = (low + high + 1) // 2
            if self.fits_text(text[:mid]):
                low = mid
            else:
                high = mid - 1
        breaks = list(re.finditer(r"[。！？!?；;\n]|\s+", text[:low]))
        if breaks and breaks[-1].end() >= low * 0.65:
            low = breaks[-1].end()
        # Qt offsets are UTF-16; do not cut a combining sequence or joined emoji.
        finder = QTextBoundaryFinder(QTextBoundaryFinder.BoundaryType.Grapheme, text)
        finder.setPosition(len(text[:low].encode("utf-16-le")) // 2)
        if not finder.isAtBoundary():
            finder.toPreviousBoundary()
        if finder.position() <= 0:
            finder.toNextBoundary()
        head = text.encode("utf-16-le")[:finder.position() * 2].decode("utf-16-le")
        return head, text[len(head):]

    def setText(self, text: str, sizing_text=None):
        measured = sizing_text if sizing_text is not None else text
        self._sizing_text = measured
        visible, overflow = (text, "") if self.fits_text(measured) else self.take_page(text)
        self.label.setText(visible)
        self.setToolTip(text if overflow else "")
        width, height = self.measured_size(measured)
        self.setFixedSize(width, min(self._height_limit, height))
        self.updateGeometry()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        cut = 10

        painter.setBrush(QColor(10, 12, 18, 210))
        painter.setPen(Qt.PenStyle.NoPen)
        poly = QPolygonF([
            QPointF(cut, 0), QPointF(w, 0), QPointF(w, h),
            QPointF(0, h),   QPointF(0, cut)
        ])
        painter.drawPolygon(poly)

        painter.setPen(QPen(QColor(180, 160, 100, 140), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolygon(poly)

        painter.setPen(QPen(QColor(220, 190, 100, 255), 1))
        painter.drawLine(cut, 0, cut + 16, 0)
        painter.drawLine(0, cut, 0, cut + 16)
        painter.end()


# ── 输入框行 ──────────────────────────────────────────────
class AKInputBar(QWidget):
    send_signal = pyqtSignal(str)
    cancel_signal = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedHeight(34)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.input_box = QLineEdit()
        self.input_box.setPlaceholderText("输入指令...")
        self.input_box.setFont(QFont("Microsoft YaHei UI", 10))
        self.input_box.setFixedHeight(34)
        self.input_box.setStyleSheet("""
            QLineEdit {
                background: rgba(10, 12, 18, 200);
                color: #e8e4d8;
                border: 1px solid rgba(180, 160, 100, 120);
                border-right: none;
                padding: 0 12px;
                selection-background-color: rgba(180, 160, 100, 80);
            }
            QLineEdit:focus {
                border: 1px solid rgba(220, 190, 100, 200);
                border-right: none;
            }
        """)
        self.input_box.returnPressed.connect(self._on_send)

        self.btn = QPushButton("发送")
        self.btn.setFixedSize(60, 34)
        self.btn.setFont(QFont("Microsoft YaHei UI", 9))
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn.setStyleSheet("""
            QPushButton {
                background: rgba(180, 155, 80, 200);
                color: #0a0c12;
                border: 1px solid rgba(220, 190, 100, 180);
                font-weight: bold;
                letter-spacing: 0px;
            }
            QPushButton:hover { background: rgba(220, 190, 100, 230); }
            QPushButton:pressed { background: rgba(140, 120, 60, 255); }
            QPushButton:disabled {
                background: rgba(60, 60, 60, 150);
                color: rgba(150, 150, 150, 150);
                border-color: rgba(80, 80, 80, 100);
            }
        """)
        self.btn.clicked.connect(self._on_send)

        layout.addWidget(self.input_box)
        layout.addWidget(self.btn)
        self.cancel_btn = QPushButton()
        self.cancel_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaStop))
        self.cancel_btn.setFixedSize(34, 34)
        self.cancel_btn.setToolTip("停止本轮回复")
        self.cancel_btn.clicked.connect(self.cancel_signal.emit)
        self.cancel_btn.setEnabled(False)
        layout.addWidget(self.cancel_btn)
        self._input_style = self.input_box.styleSheet()

    def apply_scale(self, scale):
        height = round(34 * scale)
        self.setFixedHeight(height)
        self.input_box.setFixedHeight(height)
        self.btn.setFixedSize(round(60 * scale), height)
        self.cancel_btn.setFixedSize(height, height)
        from PyQt6.QtCore import QSize
        self.cancel_btn.setIconSize(QSize(round(16 * scale), round(16 * scale)))
        self.layout().setSpacing(round(6 * scale))
        font = self.input_box.font()
        font.setPointSizeF(10 * scale)
        self.input_box.setFont(font)
        font.setPointSizeF(9 * scale)
        self.btn.setFont(font)
        self.input_box.setStyleSheet(self._input_style.replace("0 12px", "0 %spx" % round(12 * scale)))

    def _on_send(self):
        text = self.input_box.text().strip()
        if text:
            self.send_signal.emit(text)

    def clear(self):
        self.input_box.clear()

    def set_enabled(self, enabled: bool):
        self.btn.setEnabled(enabled)
        self.cancel_btn.setEnabled(not enabled)

    def text(self):
        return self.input_box.text()
