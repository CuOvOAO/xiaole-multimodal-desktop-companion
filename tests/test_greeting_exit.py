import threading
from types import SimpleNamespace
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication
from ui.window import CompanionWindow
from core.social import SessionState


def make_window(client=None):
    app = QApplication.instance() or QApplication([])
    return app, CompanionWindow(llm_client=client, initialize_sensors=False, use_memory=False)


def test_greeting_is_shared_when_client_finishes_loading():
    app, window = make_window()
    window.start_greeting(state=SessionState())
    openings = []
    client = SimpleNamespace(set_opening=lambda *args: openings.append(args), close=lambda: None)
    window._on_client_ready(client)
    assert len(openings) == 1
    assert window._opening.sentences[1]["text"] in openings[0][0]
    window.close()


def test_greeting_does_not_interrupt_a_draft():
    app, window = make_window()
    window.input_bar.input_box.setText("我已经开始打字了")
    window.start_greeting(state=SessionState())
    assert not window._greeting_active
    assert window.input_bar.text() == "我已经开始打字了"
    window.close()


def test_departure_plays_and_closes_without_network_or_client():
    app, window = make_window()
    loop = QEventLoop()
    closed = []
    window.closed.connect(lambda: (closed.append(True), loop.quit()))
    window.show()
    window._send("拜拜啦")
    assert window._farewell_active
    assert not closed
    QTimer.singleShot(4000, loop.quit)
    loop.exec()
    assert closed
    assert window._shutdown_done


def test_typing_cancels_exit_and_old_stream_cannot_end_farewell_early():
    app, window = make_window()
    window._worker = SimpleNamespace(cancelled=threading.Event(), isRunning=lambda: True)
    window._send("我先走啦")
    assert window._worker.cancelled.is_set()
    window._on_stream_finished()
    assert not window._farewell_timer.isActive()
    window._draft_edited("等等")
    assert not window._farewell_active
    assert not window._farewell_timer.isActive()
    window._worker = None
    window.close()


def test_asr_departure_is_not_stuck_behind_busy_reply():
    app, window = make_window()
    window._busy = True
    window._handle_asr_text("拜拜啦")
    window._auto_send_asr("拜拜啦")
    assert window._farewell_active
    window.close()
