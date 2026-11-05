# core/screen.py — 屏幕感知模块（视觉模型版，无 OCR）
# 依赖：mss（截图）
# 安装：pip install mss

from __future__ import annotations
import base64
import os
import time
import threading
from typing import Optional

try:
    import mss
    import mss.tools
    _MSS_OK = True
except ImportError:
    _MSS_OK = False
    print("[Screen] 警告：mss 未安装。pip install mss")


class ScreenCapture:
    """
    后台每隔 N 秒静默截一张图，缓存为最新屏幕快照。
    发消息时直接取缓存，不阻塞 UI。
    """

    def __init__(self, interval: float = 3.0):
        self._interval = interval
        self._latest_b64: Optional[str] = None
        self._captured_at = 0.0
        self.monitor = None
        self._capture_lock = threading.Lock()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

    # ── 启动/停止后台截图线程 ─────────────────────────────
    def start(self):
        if not _MSS_OK:
            print("[Screen] mss 未安装，屏幕感知不可用")
            return
        if self._running:
            return
        self._running = True
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        print(f"[Screen] 屏幕感知已启动（每 {self._interval}s 刷新）")

    def stop(self):
        self._running = False
        self._stop.set()

    def _loop(self):
        while self._running:
            try:
                b64 = self._capture_b64()
                with self._lock:
                    self._latest_b64 = b64
                    self._captured_at = time.monotonic()
            except Exception as e:
                print(f"[Screen] 截图异常：{e}")
            self._stop.wait(self._interval)

    # ── 截图并转 base64 ───────────────────────────────────
    def _capture_b64(self) -> str:
        import io
        from PIL import Image
        with mss.mss() as sct:
            index = int(os.getenv("SCREEN_MONITOR", "1"))
            if not 1 <= index < len(sct.monitors):
                raise ValueError("SCREEN_MONITOR 指向不存在的显示器")
            mon = sct.monitors[index]
            self.monitor = dict(mon)
            img = sct.grab(mon)
            # 不放大小屏幕；JPEG 压缩只在采集线程执行。
            pil_img = Image.frombytes("RGB", img.size, img.rgb)
            w, h = pil_img.size
            new_w = min(960, w)
            new_h = int(h * new_w / w)
            pil_img = pil_img.resize((new_w, new_h), Image.LANCZOS)
            buf = io.BytesIO()
            pil_img.save(buf, format="JPEG", quality=85)
            return base64.b64encode(buf.getvalue()).decode("utf-8")
    # ── 获取最新截图 ──────────────────────────────────────
    def get_latest_b64(self, max_age: float = 5.0) -> Optional[str]:
        with self._lock:
            return self._latest_b64 if time.monotonic() - self._captured_at <= max_age else None

    def capture_b64(self) -> str:
        cached = self.get_latest_b64(max_age=1.5)
        if cached:
            return cached
        with self._capture_lock:
            fresh = self._capture_b64()
            with self._lock:
                self._latest_b64 = fresh
                self._captured_at = time.monotonic()
            return fresh

    @property
    def available(self) -> bool:
        return _MSS_OK and self.get_latest_b64() is not None


# ── 模块级单例 ────────────────────────────────────────────
_capture: Optional[ScreenCapture] = None

def get_screen_capture() -> ScreenCapture:
    global _capture
    if _capture is None:
        _capture = ScreenCapture(interval=3.0)
    return _capture
