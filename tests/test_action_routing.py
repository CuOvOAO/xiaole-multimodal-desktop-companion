import json
import threading
from types import SimpleNamespace

import pytest
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtTest import QTest

from core.action_router import direct_request, validate_action
from core.context import action_intent
from ui.window import CompanionWindow
from ui.workers import LLMWorker


@pytest.mark.parametrize("text,target", [
    ("帮我打开记事本", "notepad"), ("打开计算器", "calc"),
    ("小乐，请帮我打开记事本吧", "notepad"), ("你打开记事本", "notepad"),
    ("你把记事本打开", "notepad"), ("可以帮我打开浏览器吗", "browser"),
    ("打开 https://example.com", "https://example.com"),
])
def test_explicit_open_is_deterministic(text, target):
    result = direct_request(text)
    assert result.action == {"type": "open", "target": target}
    assert action_intent(text)


@pytest.mark.parametrize("text", ["不要打开记事本", "如果打开记事本会怎样", "你会打开记事本吗", "请翻译打开记事本", '他说"打开记事本"', "打开记事本并输入hello"])
def test_hypothetical_quoted_negated_or_composite_is_not_a_direct_open(text):
    assert direct_request(text) is None


def test_retry_uses_only_user_requested_target_or_clarifies():
    assert action_intent("你快打开呀")
    assert direct_request("你快打开呀").clarification
    assert direct_request("你快打开呀", {"type": "open", "target": "notepad"}).action["target"] == "notepad"
    assert direct_request("你快打开呀", {"type": "search", "query": "test"}).clarification


def test_search_matches_literal_query_and_preserves_multi_step_opt_in():
    assert direct_request("去维基百科搜蕾缪乐").action == {"type": "search", "query": "蕾缪乐", "engine": "wikipedia"}
    assert direct_request("搜索打开记事本的方法").action["query"] == "打开记事本的方法"
    assert direct_request("搜索蕾缪乐并打开第一条结果") is None


@pytest.mark.parametrize("action", [{}, {"type": "open"}, {"type": "search", "query": ""},
                                   {"type": "click", "x": True, "y": 2}, {"type": "hotkey", "keys": []},
                                   {"type": "open", "target": "file:///test"}])
def test_incomplete_actions_fail_closed(action):
    with pytest.raises(ValueError):
        validate_action(action)


def test_model_promise_without_action_is_visible_failure_not_speech():
    calls, speech, missing, actions = [], [], [], []
    def stream(*args, **kwargs):
        calls.append(kwargs)
        yield {"text": "已经打开了，老板！", "emotion": "happy"}
    worker = LLMWorker(SimpleNamespace(chat_stream=stream), "帮我打开未知应用")
    worker.sentence_ready.connect(lambda text, *args: speech.append(text))
    worker.action_missing.connect(missing.append)
    worker.action_ready.connect(actions.append)
    worker.run()
    assert calls[0]["record_turn"] is False and calls[0]["preview_callback"] is None
    assert missing and "未执行" in speech[0] and not actions
    assert not any("已经打开" in text for text in speech)


def test_planner_action_is_separate_from_speech_and_not_repeated():
    action = {"type": "open", "target": "notepad"}
    client = SimpleNamespace(chat_stream=lambda *a, **kw: iter([
        {"text": "我马上打开", "emotion": "happy", "action": action},
        {"text": "已经打开啦", "emotion": "happy", "action": action},
    ]))
    worker = LLMWorker(client, "帮我打开记事本")
    actions, speech = [], []
    worker.action_ready.connect(lambda raw: actions.append(json.loads(raw)))
    worker.sentence_ready.connect(lambda text, emotion, raw: speech.append((text, raw)))
    worker.run()
    assert actions == [action]
    assert speech == [("操作指令已就绪。", "")]


def test_window_to_real_action_worker_to_launcher_without_model_or_real_launch(monkeypatch):
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    launches, records = [], []
    main_thread = threading.get_ident()
    def fake_launch(argv, **kwargs):
        launches.append((argv, kwargs, threading.get_ident()))
        return SimpleNamespace(poll=lambda: None)
    monkeypatch.setattr("core.desktop.Path.is_file", lambda _: True)
    monkeypatch.setattr("core.desktop.subprocess.Popen", fake_launch)
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    def forbidden(*args, **kwargs):
        raise AssertionError("Simple actions must not call the language model")
    client = SimpleNamespace(chat_stream=forbidden, record_action=records.append,
                             record_tool_turn=lambda *a: None, close=lambda: None)
    window = CompanionWindow(llm_client=client, initialize_sensors=False, use_memory=False)
    try:
        window._send("帮我打开记事本")
        for _ in range(200):
            QTest.qWait(10)
            if not window._action_workers:
                break
        assert not window._action_workers and not window._busy
        assert len(launches) == 1 and launches[0][0][0].endswith("notepad.exe")
        assert launches[0][1]["shell"] is False and launches[0][2] != main_thread
        assert records and "启动请求" in records[-1]
        assert "启动请求" in window.status_label.text()
    finally:
        window.close()


def test_direct_cancel_and_missing_target_are_reported_without_model(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.No)
    window = CompanionWindow(initialize_sensors=False, use_memory=False)
    window._send("你快打开呀")
    assert "哪个应用" in window.bubble.label.text() and not window._busy
    window._send("打开记事本")
    assert "取消" in window.status_label.text() and not window._action_workers and not window._busy
    window.close()


def test_search_full_pipeline_does_not_request_confirmation_or_click(monkeypatch):
    app = QApplication.instance() or QApplication([])
    urls = []
    monkeypatch.setattr("core.desktop.webbrowser.open", lambda url: urls.append(url) or True)
    def forbidden(*args):
        raise AssertionError("Ordinary search must neither confirm nor click")
    monkeypatch.setattr(QMessageBox, "question", forbidden)
    monkeypatch.setattr("core.desktop.HumanLikeController.click_first_result", forbidden)
    window = CompanionWindow(initialize_sensors=False, use_memory=False)
    try:
        window._send("去维基百科搜蕾缪乐")
        for _ in range(200):
            QTest.qWait(10)
            if not window._action_workers:
                break
        assert len(urls) == 1 and "wikipedia" in urls[0]
        assert not window._busy and "已搜索" in window.status_label.text()
    finally:
        window.close()


def test_action_confirmation_keeps_busy_and_cancel_unlocks(monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = CompanionWindow(initialize_sensors=False, use_memory=False)
    window._lock()
    def decline(*args):
        window._unlock()  # A queued stream-finished signal can arrive inside the modal.
        assert window._busy
        return QMessageBox.StandardButton.No
    monkeypatch.setattr(QMessageBox, "question", decline)
    window._on_action_ready('{"type":"open","target":"notepad"}')
    assert not window._busy and "取消" in window.status_label.text()
    window.close()
