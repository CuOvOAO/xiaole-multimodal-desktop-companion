import time
from core.screen import ScreenCapture
from core.camera import CameraCapture


def test_stale_screen_cache_is_not_used():
    capture = ScreenCapture()
    capture._latest_b64 = "old"
    capture._captured_at = time.monotonic() - 10
    assert capture.get_latest_b64(max_age=2) is None


def test_fresh_cache_avoids_duplicate_screen_capture(monkeypatch):
    capture = ScreenCapture()
    capture._latest_b64 = "fresh"
    capture._captured_at = time.monotonic()
    monkeypatch.setattr(capture, "_capture_b64", lambda: "unneeded")
    assert capture.capture_b64() == "fresh"


def test_camera_failure_never_returns_old_picture(monkeypatch):
    camera = CameraCapture()
    camera._latest_b64 = "old"
    monkeypatch.setattr(camera, "_grab_b64", lambda: None)
    assert camera.capture_b64() == ""


def test_camera_success_is_returned_from_background(monkeypatch):
    camera = CameraCapture()
    monkeypatch.setattr(camera, "_grab_b64", lambda: "fresh")
    assert camera.capture_b64() == "fresh"
