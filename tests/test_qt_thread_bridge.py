import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from ui.window import CompanionWindow


def make_window(monkeypatch):
    for method in ("_init_screen_capture", "_init_camera", "_init_asr", "_init_screen_watcher"):
        monkeypatch.setattr(CompanionWindow, method, lambda self: None)
    app = QApplication.instance() or QApplication([])
    return app, CompanionWindow(llm_client=None)


def test_asr_signal_crosses_from_python_thread(monkeypatch):
    monkeypatch.setattr(CompanionWindow, "_init_screen_capture", lambda self: None)
    monkeypatch.setattr(CompanionWindow, "_init_camera", lambda self: None)
    monkeypatch.setattr(CompanionWindow, "_init_asr", lambda self: None)
    monkeypatch.setattr(CompanionWindow, "_init_screen_watcher", lambda self: None)

    app = QApplication.instance() or QApplication([])
    window = CompanionWindow(llm_client=None)
    threading.Thread(
        target=lambda: window.asr_text_received.emit("语音线程测试")
    ).start()
    QTimer.singleShot(150, app.quit)
    app.exec()

    assert window.input_bar.text() == "语音线程测试"
    window.close()


def test_asr_does_not_replace_typed_draft(monkeypatch):
    app, window = make_window(monkeypatch)
    window.input_bar.input_box.setText("typed")
    window._handle_asr_text("voice")
    assert window.input_bar.text() == "typed"
    assert window._pending_asr == "voice"
    window.close()


def test_busy_user_can_still_edit_input(monkeypatch):
    app, window = make_window(monkeypatch)
    window._lock()
    assert window.input_bar.input_box.isEnabled()
    assert not window.input_bar.btn.isEnabled()
    window._handle_asr_text("voice")
    assert window.input_bar.text() == "voice"
    window.close()


def test_editing_asr_draft_invalidates_auto_send(monkeypatch):
    app, window = make_window(monkeypatch)
    sent = []
    monkeypatch.setattr(window, "_send", lambda *args, **kwargs: sent.append(args))
    window._handle_asr_text("voice")
    window._draft_edited("voice")
    window._auto_send_asr("voice")
    assert not sent
    window.close()


def test_background_client_ready_preserves_typed_input(monkeypatch):
    from types import SimpleNamespace
    app, window = make_window(monkeypatch)
    window.input_bar.input_box.setText("draft during loading")
    closed = []
    client = SimpleNamespace(close=lambda: closed.append(True))
    window._on_client_ready(client)
    assert window.llm_client is client
    assert window.input_bar.text() == "draft during loading"
    assert window.input_bar.btn.isEnabled()
    window.close()
    assert closed

