#立绘管理
# ui/avatar.py — 立绘情绪管理器（支持裁剪比例）

from pathlib import Path
from PyQt6.QtWidgets import QLabel
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QRect

AVATAR_DIR = Path(__file__).parent.parent / "assets" / "avatars"

EMOTION_MAP = {
    "neutral":   "neutral.png",
    "happy":     "happy.png",
    "sad":       "sad.png",
    "surprised": "surprised.png",
    "angry":     "angry.png",
    "thinking":  "thinking.png",
    "shy":       "shy.png",
}
FALLBACK = "neutral"


class AvatarManager:
    """
    立绘管理器。
    crop_ratio: 只显示图片上方这个比例的内容（0.72 = 截到大腿根附近）
    """

    def __init__(self, label: QLabel, size: tuple[int, int] = (300, 450),
                 crop_ratio: float = 1.0):
        self.label = label
        self.size = size
        self.crop_ratio = crop_ratio  # 显示图片上方多少比例
        self._current_emotion = None
        self._cache = {}
        self._source_cache = {}
        self._fade_out_anim = None
        self._fade_in_anim = None

        self.label.setAlignment(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter)
        self.label.setFixedSize(*size)
        self.label.setStyleSheet("background: transparent;")

        self.set_emotion("neutral", animate=False)

    def set_emotion(self, emotion: str, animate: bool = True):
        emotion = emotion.lower().strip()
        if emotion not in EMOTION_MAP:
            emotion = FALLBACK
        if emotion == self._current_emotion:
            return

        img_path = AVATAR_DIR / EMOTION_MAP[emotion]
        if not img_path.exists():
            print(f"[AvatarManager] 找不到 {img_path}，回退 neutral")
            img_path = AVATAR_DIR / EMOTION_MAP[FALLBACK]
            emotion = FALLBACK

        pixmap = self._load_and_crop(str(img_path))

        if animate:
            self._fade_switch(pixmap)
        else:
            self.label.setPixmap(pixmap)

        self._current_emotion = emotion

    def set_size(self, size):
        if self.size == size:
            return
        for animation in (self._fade_out_anim, self._fade_in_anim):
            if animation:
                animation.stop()
        if self.label.graphicsEffect():
            self.label.graphicsEffect().setOpacity(1.0)
        self.size = size
        self.label.setFixedSize(*size)
        self._cache.clear()
        emotion = self.current_emotion
        self._current_emotion = None
        self.set_emotion(emotion, animate=False)

    def _load_and_crop(self, path: str) -> QPixmap:
        """加载图片，按 crop_ratio 裁掉底部，再缩放到 size。"""
        if path in self._cache:
            return self._cache[path]
        raw = self._source_cache.get(path)
        if raw is None:
            raw = self._load_source(path)
            self._source_cache[path] = raw
        pixmap = raw.scaled(
            *self.size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._cache[path] = pixmap
        return pixmap

    def _load_source(self, path):
        """Decode and crop once, not on every wheel tick."""
        raw = QPixmap(path)
        if raw.isNull():
            return raw

        # 自动裁掉四周透明边距
        from PIL import Image
        with Image.open(path) as image:
            box = image.convert("RGBA").getchannel("A").point(lambda a: 255 if a > 10 else 0).getbbox()
        if box:
            raw = raw.copy(QRect(box[0], box[1], box[2] - box[0], box[3] - box[1]))
        # 再裁掉底部
        if self.crop_ratio < 1.0:
            crop_h = int(raw.height() * self.crop_ratio)
            raw = raw.copy(QRect(0, 0, raw.width(), crop_h))

        return raw

    @property
    def current_emotion(self) -> str:
        return self._current_emotion or FALLBACK

    def _fade_switch(self, new_pixmap: QPixmap):
        from PyQt6.QtWidgets import QGraphicsOpacityEffect

        for animation in (self._fade_out_anim, self._fade_in_anim):
            if animation:
                animation.stop()
        effect = self.label.graphicsEffect()
        if effect is None:
            effect = QGraphicsOpacityEffect(self.label)
            self.label.setGraphicsEffect(effect)

        fade_out = QPropertyAnimation(effect, b"opacity")
        fade_out.setDuration(120)
        fade_out.setStartValue(effect.opacity())
        fade_out.setEndValue(0.0)
        fade_out.setEasingCurve(QEasingCurve.Type.OutCubic)

        def on_done():
            self.label.setPixmap(new_pixmap)
            fade_in = QPropertyAnimation(effect, b"opacity")
            fade_in.setDuration(180)
            fade_in.setStartValue(0.0)
            fade_in.setEndValue(1.0)
            fade_in.setEasingCurve(QEasingCurve.Type.InCubic)
            fade_in.start()
            self._fade_in_anim = fade_in

        fade_out.finished.connect(on_done)
        fade_out.start()
        self._fade_out_anim = fade_out
