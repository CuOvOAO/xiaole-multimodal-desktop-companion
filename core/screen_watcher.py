"""Local pixel changes trigger low-priority visual observations, never desktop actions."""
import base64
import io
import logging
import threading
import time
import numpy as np
from PIL import Image
from config import SCREEN_WATCH_PROMPT
from core.protocol import parse_response
from core.vision import VisionBusy


class ScreenWatcher:
    CHANGE_THRESHOLD = 0.08
    COOLDOWN_SECONDS = 45
    EVALUATION_COOLDOWN = 30
    CHECK_INTERVAL = 3.0
    CAPTURE_WIDTH = 320

    def __init__(self, on_change, llm_client=None, screen_capture=None):
        self._on_change = on_change
        self._llm_client = llm_client
        self._screen_capture = screen_capture
        self.can_observe = lambda: True
        self.exclude_rect = None
        self._stop = threading.Event()
        self._running = False
        self._prev_frame = None
        self._last_speak_time = self._last_eval_time = 0.0

    def start(self):
        if self._running or not self._llm_client:
            return
        self._running = True
        self._stop.clear()
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self._running = False
        self._stop.set()

    def _loop(self):
        while not self._stop.wait(self.CHECK_INTERVAL):
            try:
                if not self.can_observe():
                    self._prev_frame = None
                    continue
                frame, image = self._capture()
                if frame is None:
                    continue
                changed = self._prev_frame is not None and self._diff_ratio(self._prev_frame, frame) >= self.CHANGE_THRESHOLD
                self._prev_frame = frame
                now = time.monotonic()
                if not changed or not self.can_observe():
                    continue
                if now - self._last_speak_time < self.COOLDOWN_SECONDS or now - self._last_eval_time < self.EVALUATION_COOLDOWN:
                    continue
                self._last_eval_time = now
                sentences = self._ask_llm(image)
                if sentences and not self._stop.is_set() and self.can_observe():
                    self._last_speak_time = time.monotonic()
                    self._llm_client.observations.update(" ".join(s["text"] for s in sentences), "近期屏幕观察")
                    self._on_change(sentences)
            except Exception as exc:
                logging.warning("Screen watcher failed: %s", type(exc).__name__)

    def _capture(self):
        if not self._screen_capture:
            return None, ""
        image = self._screen_capture.get_latest_b64(max_age=5)
        if not image:
            return None, ""
        with Image.open(io.BytesIO(base64.b64decode(image))) as source:
            small = source.convert("RGB")
            small.thumbnail((self.CAPTURE_WIDTH, self.CAPTURE_WIDTH))
            frame = np.asarray(small).copy()
        # Mask our own window so bubble typing and avatar changes do not trigger commentary.
        rect = self.exclude_rect
        monitor = self._screen_capture.monitor
        if rect and monitor:
            x, y, w, h = rect
            sx, sy = frame.shape[1] / monitor["width"], frame.shape[0] / monitor["height"]
            x1, y1 = max(0, int((x - monitor["left"]) * sx)), max(0, int((y - monitor["top"]) * sy))
            x2 = min(frame.shape[1], int((x + w - monitor["left"]) * sx))
            y2 = min(frame.shape[0], int((y + h - monitor["top"]) * sy))
            if x2 > x1 and y2 > y1:
                frame[y1:y2, x1:x2] = 0
        return frame, image

    @staticmethod
    def _diff_ratio(img1, img2):
        if img1.shape != img2.shape:
            return 1.0
        return float((np.abs(img1.astype(np.int16) - img2.astype(np.int16)) > 30).mean())

    def _ask_llm(self, image):
        try:
            raw = self._llm_client.vision_chat_local(SCREEN_WATCH_PROMPT, image, background=True)
            sentences = parse_response(raw)["sentences"]
            # No actions from untrusted ambient screen content.
            return [{key: s[key] for key in ("text", "emotion")} for s in sentences[:2]] or None
        except VisionBusy:
            return None
        except Exception as exc:
            logging.warning("Background vision failed: %s", type(exc).__name__)
            return None


_watcher = None


def get_screen_watcher(on_change, llm_client=None, screen_capture=None):
    global _watcher
    if _watcher is None:
        _watcher = ScreenWatcher(on_change, llm_client, screen_capture)
    else:
        _watcher._on_change = on_change
        _watcher._llm_client = llm_client
        _watcher._screen_capture = screen_capture
    return _watcher
