import json
from types import SimpleNamespace

import pytest

from core.desktop import HumanLikeController
from ui.workers import ActionWorker, LLMWorker


def test_search_does_not_click_without_opt_in(monkeypatch):
    controller = HumanLikeController()
    clicks = []
    monkeypatch.setattr("core.desktop.webbrowser.open", lambda url: True)
    monkeypatch.setattr("core.desktop.time.sleep", lambda seconds: None)
    monkeypatch.setattr(controller, "click_first_result", lambda: clicks.append(True) or "clicked")
    assert "未自动点击" in controller.search_web("测试")
    assert not clicks
    controller.search_web("测试", open_first=True)
    assert clicks == [True]


@pytest.mark.parametrize("user_text,flag", [("搜索小乐", False), ("搜索小乐并打开第一条结果", True),
                                         ("搜索小乐，不要点开第一条结果", False)])
def test_worker_cannot_invent_first_result_permission(user_text, flag):
    sentence = {"text": "试试", "emotion": "neutral", "action": {"type": "search", "query": "小乐", "open_first": True}}
    worker = LLMWorker(SimpleNamespace(chat_stream=lambda *a, **kw: iter([sentence])), user_text)
    received = []
    worker.action_ready.connect(lambda action: received.append(json.loads(action)))
    worker.run()
    assert received[0]["open_first"] is flag
    assert sentence["action"]["open_first"] is True


@pytest.mark.parametrize("focused,expected", [(False, 0), (True, 1)])
def test_keyboard_action_waits_and_checks_external_focus(monkeypatch, focused, expected):
    calls, waits, messages = [], [], []
    monkeypatch.setattr("core.desktop_focus.external_window_focused", lambda: focused)
    monkeypatch.setattr("core.desktop.execute_action", lambda *args: calls.append(args) or "done")
    worker = ActionWorker({"type": "type", "text": "hello"})
    monkeypatch.setattr(worker.cancelled, "wait", lambda seconds: waits.append(seconds) or False)
    worker.completed.connect(messages.append)
    worker.run()
    assert waits == [3.0]
    assert len(calls) == expected
    assert messages


def test_keyboard_wait_can_be_cancelled(monkeypatch):
    calls = []
    monkeypatch.setattr("core.desktop.execute_action", lambda *args: calls.append(args))
    worker = ActionWorker({"type": "hotkey", "keys": ["ctrl", "l"]})
    monkeypatch.setattr(worker.cancelled, "wait", lambda seconds: True)
    worker.run()
    assert not calls
