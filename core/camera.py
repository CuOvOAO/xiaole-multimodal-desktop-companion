# core/camera.py — 摄像头视觉模块
# 通过前置摄像头让小乐"看见"用户本人。
# 依赖：opencv-python
# 安装：pip install opencv-python

from __future__ import annotations
import base64
import logging
import threading
import time
from typing import Optional

try:
    import cv2
    _CV_OK = True
except ImportError:
    _CV_OK = False
    print("[Camera] 警告：opencv-python 未安装。pip install opencv-python")


FRAME_WIDTH = 640      # 输出帧宽（缩放后）
JPEG_QUALITY = 85
REFRESH_INTERVAL = 5.0  # 后台缓存刷新间隔（秒）
CAMERA_INDEX = 0        # 默认摄像头


class CameraCapture:
    """
    后台每隔 N 秒抓一帧缓存。需要时立即抓一帧返回 base64。
    摄像头按需打开，长期不用时不独占设备。
    """

    def __init__(self, interval: float = REFRESH_INTERVAL):
        self._interval = interval
        self._latest_b64: Optional[str] = None
        self._captured_at = 0.0
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._cap_lock = threading.Lock()
        self._device_available: Optional[bool] = None
        self._request_lock = threading.Lock()
        self._request_event = None
        self._request_result = ""

    # ── 启动/停止后台抓帧线程 ─────────────────────────────
    def start(self):
        if not _CV_OK:
            print("[Camera] opencv 未安装，摄像头不可用")
            return
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        print(f"[Camera] 摄像头已启动（每 {self._interval}s 刷新）")

    def stop(self):
        self._running = False

    def _loop(self):
        # 首帧前给摄像头一点预热时间
        while self._running:
            try:
                b64 = self._grab_b64()
                if b64:
                    with self._lock:
                        self._latest_b64 = b64
                        self._captured_at = time.monotonic()
            except Exception as e:
                print(f"[Camera] 抓帧异常：{e}")
            time.sleep(self._interval)

    # ── 抓一帧 → JPEG base64 ─────────────────────────────
    def _grab_b64(self) -> Optional[str]:
        if not _CV_OK:
            return None
        with self._cap_lock:
            cap = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_DSHOW)
            try:
                if not cap.isOpened():
                    self._device_available = False
                    return None
                # 丢弃预热帧，避免刚打开时曝光未稳定。
                ok, frame = False, None
                for _ in range(3):
                    ok, frame = cap.read()
                self._device_available = bool(ok and frame is not None)
            finally:
                cap.release()
        if not ok or frame is None:
            return None

        h, w = frame.shape[:2]
        if w > FRAME_WIDTH:
            new_h = int(h * FRAME_WIDTH / w)
            frame = cv2.resize(frame, (FRAME_WIDTH, new_h), interpolation=cv2.INTER_AREA)

        ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        if not ok:
            return None
        return base64.b64encode(jpg.tobytes()).decode("utf-8")

    # ── 立即抓一帧（优先用缓存的最新帧，否则现抓）────────
    def capture_b64(self) -> str:
        # A stuck native driver must not keep the conversation QThread alive indefinitely.
        with self._request_lock:
            if self._request_event is None or self._request_event.is_set():
                event = threading.Event()
                self._request_event = event
                self._request_result = ""
                def grab():
                    try:
                        fresh = self._grab_b64() or ""
                        with self._request_lock:
                            self._request_result = fresh
                            self._captured_at = time.monotonic()
                    except Exception as exc:
                        logging.warning("Camera driver failed: %s", type(exc).__name__)
                    finally:
                        event.set()
                threading.Thread(target=grab, daemon=True).start()
            event = self._request_event
        if not event.wait(3):
            return ""
        with self._request_lock:
            return self._request_result if time.monotonic() - self._captured_at < 2 else ""

    def available(self) -> bool:
        if not _CV_OK:
            return False
        if self._device_available is not None:
            return self._device_available
        with self._cap_lock:
            cap = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_DSHOW)
            try:
                self._device_available = cap.isOpened()
            finally:
                cap.release()
        return self._device_available


# ── 模块级单例 ────────────────────────────────────────────
_camera: Optional[CameraCapture] = None

def get_camera_capture() -> CameraCapture:
    global _camera
    if _camera is None:
        _camera = CameraCapture()
    return _camera
