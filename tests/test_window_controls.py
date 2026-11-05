import json
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QApplication, QMessageBox

from core.companion_commands import companion_command, first_result_requested
from ui.preferences import WindowPreferences
from ui.window import CompanionWindow
from ui.window_controls import WindowControls


@pytest.fixture
def window():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    window = CompanionWindow(initialize_sensors=False, use_memory=False)
    window.show()
    app.processEvents()
    yield window
    window.close()
    app.processEvents()


@pytest.mark.parametrize("text,command", [
    ("小乐，变小一点吧！", "smaller"), ("请放大一些", "larger"),
    ("恢复默认大小", "reset_size"), ("安静陪我", "quiet"),
    ("恢复主动聊天", "talk"), ("你挪到屏幕左下角", "left"),
    ("靠右边", "right"), ("把浏览器缩小一点", None),
    ("不要变小", None), ("我说过变小一点", None),
    ("如果你变小一点会怎样？", None), ("搜索安静陪我", None),
])
def test_only_exact_self_commands(text, command):
    assert companion_command(text) == command


@pytest.mark.parametrize("text,expected", [
    ("在维基搜蕾缪乐并打开第一条结果", True),
    ("点击第1个链接", True), ("搜索蕾缪乐", False),
    ("不要打开第一条结果", False), ("搜索包含‘打开第一条结果’的文章", False),
    ("如果点开第一条结果会怎么样", False),
])
def test_first_link_requires_explicit_request(text, expected):
    assert first_result_requested(text) is expected


def test_preferences_roundtrip_and_invalid_values(tmp_path):
    path = tmp_path / "preferences.json"
    prefs = WindowPreferences(path)
    assert prefs.scale == 1 and prefs.quiet and prefs.position is None
    prefs.scale, prefs.quiet, prefs.position = 1.25, False, [-50, 80]
    prefs.save()
    restored = WindowPreferences(path)
    assert (restored.scale, restored.quiet, restored.position) == (1.25, False, [-50, 80])
    path.write_text('{"scale": NaN, "quiet": "false", "position": [true, 0]}')
    invalid = WindowPreferences(path)
    assert invalid.scale == 1 and invalid.quiet and invalid.position is None
    path.write_text("broken json")
    assert WindowPreferences(path).quiet
    path.write_text('{"scale": 100}')
    assert WindowPreferences(path).scale == 1.75


@pytest.mark.parametrize("scale", [0.7, 1.0, 1.25, 1.75])
def test_proportional_layout_and_crop_seam(window, monkeypatch, scale):
    controls = window._controls
    monkeypatch.setattr(controls, "screen_rect", lambda *_: QRect(0, 0, 3840, 2160))
    controls.set_scale(scale)
    window._show_bubble("老板，我在这里。" * 5)
    QApplication.processEvents()
    avatar, bubble, input_bar = (w.geometry() for w in (window.avatar_label, window.bubble, window.input_bar))
    assert controls.scale == pytest.approx(scale)
    assert window.width() == round(controls._base_size.width() * scale)
    assert window.bubble.label.font().pointSizeF() == pytest.approx(10 * scale)
    assert window.input_bar.height() == round(34 * scale)
    assert bubble.top() == avatar.bottom() + 1
    assert bubble.left() < avatar.left() and bubble.right() > avatar.right()
    assert input_bar.top() > bubble.bottom()
    assert input_bar.bottom() < window.height()
    label = window.bubble.label
    assert label.height() >= label.heightForWidth(label.width())
    assert not window.avatar_label.pixmap().isNull()


def test_scale_fits_screen_and_restores_preferences(window, monkeypatch, tmp_path):
    controls = window._controls
    screen = QRect(-800, 0, 800, 600)
    monkeypatch.setattr(controls, "screen_rect", lambda *_: screen)
    controls.set_scale(100)
    assert screen.contains(window.geometry())
    assert window.height() <= 584
    controls.dock("left")
    assert screen.contains(window.geometry())
    assert window.x() == -788
    controls.preferences.path = tmp_path / "prefs.json"
    controls.save()
    prefs = WindowPreferences(controls.preferences.path)
    assert prefs.position == [window.x(), window.y()]
    assert prefs.quiet


def wheel(widget, modifiers=Qt.KeyboardModifier.NoModifier):
    point = widget.rect().center()
    return QWheelEvent(QPointF(point), QPointF(widget.mapToGlobal(point)), QPoint(), QPoint(0, 120),
                       Qt.MouseButton.NoButton, modifiers, Qt.ScrollPhase.NoScrollPhase, False)


def settle(controls):
    for _ in range(100):
        if not controls._apply_timer.isActive():
            return
        controls._last_frame -= 0.016
        controls._apply_pending()
    raise AssertionError("Zoom failed to settle")


def test_wheel_only_on_avatar_or_with_ctrl(window, monkeypatch):
    controls = window._controls
    monkeypatch.setattr(controls, "screen_rect", lambda *_: QRect(0, 0, 3840, 2160))
    window._show_bubble("测试")
    QApplication.processEvents()
    assert QApplication.sendEvent(window.avatar_label, wheel(window.avatar_label))
    settle(controls)
    assert controls.scale == pytest.approx(1.1)
    assert not controls.eventFilter(window.input_bar.input_box, wheel(window.input_bar.input_box))
    assert controls.scale == pytest.approx(1.1)
    assert controls.eventFilter(window.input_bar.input_box, wheel(window.input_bar.input_box, Qt.KeyboardModifier.ControlModifier))
    settle(controls)
    assert controls.scale == pytest.approx(1.21)
    controls.set_scale(1)
    assert controls.scale == 1


def test_event_filter_ignores_partially_destroyed_owner():
    owner = SimpleNamespace()
    assert not WindowControls.eventFilter(owner, None, None)


def test_pinch_uses_total_factor_only_once_and_cancel_restores(window, monkeypatch):
    controls = window._controls
    monkeypatch.setattr(controls, "screen_rect", lambda *_: QRect(0, 0, 3840, 2160))
    def gesture(state, factor):
        return SimpleNamespace(state=lambda: state, totalScaleFactor=lambda: factor, hasHotSpot=lambda: False)
    controls.handle_pinch(gesture(Qt.GestureState.GestureStarted, 1.1))
    controls.handle_pinch(gesture(Qt.GestureState.GestureUpdated, 1.2))
    assert controls._target_scale == pytest.approx(1.2)
    settle(controls)
    assert controls.scale == pytest.approx(1.2)
    controls.handle_pinch(gesture(Qt.GestureState.GestureCanceled, 1.2))
    assert controls.scale == pytest.approx(1)
    event = SimpleNamespace(type=lambda: QEvent.Type.NativeGesture,
                            gestureType=lambda: Qt.NativeGestureType.ZoomNativeGesture,
                            value=lambda: 0.1, globalPosition=lambda: QPointF(window.geometry().center()),
                            accept=lambda: None)
    assert controls.eventFilter(window, event)
    settle(controls)
    assert controls.scale == pytest.approx(1.1)


def test_quiet_mode_discards_pending_comments_but_local_commands_work_without_model(window):
    assert window._quiet_mode and not window._can_observe()
    window._handle_screen_change([{"text": "不能弹出", "emotion": "neutral"}])
    assert not window._sentence_player.is_playing()
    window._send("变小一点")
    settle(window._controls)
    assert window._controls.scale < 1
    assert window._sentence_player.is_playing()
    window._send("安静陪我")
    assert window._quiet_mode
    window._sentence_player.stop()
    window._busy = False
    window._last_user_activity = 0
    window._set_quiet(False)
    assert window._can_observe()
    window._pending_proactive.append((0, []))
    window._set_quiet(True)
    assert not window._pending_proactive and not window._can_observe()


def test_pet_interaction_does_not_interrupt_draft_or_reply(window):
    window.input_bar.input_box.setText("还没写完")
    window._pet_interact()
    assert window._pet_count == 0
    window.input_bar.clear()
    window._busy = True
    window._pet_interact()
    assert window._pet_count == 0
    window._busy = False
    window._pet_interact()
    assert window._pet_count == 1 and window._sentence_player.is_playing()
    window._sentence_player.stop()
    window._busy = False
    window._pet_interact()
    assert window._pet_count == 1


def test_reflow_keeps_text_and_executes_action_once(window, monkeypatch):
    actions = []
    monkeypatch.setattr(window, "_execute_action_async", actions.append)
    player = window._sentence_player
    text = "这段文字用于检查尺寸改变以后仍能完整翻页。" * 6
    window._lock()
    player.play([{"text": text, "emotion": "neutral", "action": {"type": "search", "query": "测试"}}])
    window.bubble.set_maximum_extent(260, 100)
    player.reflow()
    pages = []
    for _ in range(100):
        if player._type_timer.isActive():
            player._index = len(player._current_text)
            player._type_next_char()
            pages.append(window.bubble.label.text())
        elif player._queue:
            player._play_next()
        else:
            break
    assert "".join(pages) == text
    assert actions == [{"type": "search", "query": "测试"}]
    assert not window._busy
    player.reflow()
    assert len(actions) == 1
    player.stop()
    assert not player._queue


@pytest.mark.parametrize("kind", ["open", "click", "type", "hotkey", "scroll"])
def test_all_external_actions_require_confirmation(window, monkeypatch, kind):
    asked, started = [], []
    def decline(*args):
        asked.append(args)
        return QMessageBox.StandardButton.No
    monkeypatch.setattr(QMessageBox, "question", decline)
    monkeypatch.setattr(window, "_start_next_action", lambda: started.append(True))
    action = {"open": {"target": "notepad"}, "click": {"x": 1, "y": 1},
              "type": {"text": "hello"}, "hotkey": {"keys": ["ctrl", "l"]},
              "scroll": {"direction": "down"}}[kind]
    action = dict(action, type=kind)
    window._execute_action_async(action)
    assert asked and not started and not window._action_queue
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    window._execute_action_async(action)
    assert started and window._action_queue == [action]


def test_search_skips_confirmation_but_first_result_click_does_not(window, monkeypatch):
    asked, started = [], []
    monkeypatch.setattr(QMessageBox, "question", lambda *args: asked.append(True) or QMessageBox.StandardButton.No)
    monkeypatch.setattr(window, "_start_next_action", lambda: started.append(True))
    window._execute_action_async({"type": "search", "query": "测试"})
    assert not asked and started
    window._action_queue.clear()
    window._execute_action_async({"type": "search", "query": "测试", "open_first": True})
    assert asked and not window._action_queue


def test_zoom_moves_through_intermediate_sizes_and_reflows_once(window, monkeypatch):
    controls = window._controls
    monkeypatch.setattr(controls, "screen_rect", lambda *_: QRect(0, 0, 3840, 2160))
    calls = []
    monkeypatch.setattr(window._sentence_player, "reflow", lambda: calls.append(True))
    controls.request_scale(1.3)
    assert controls.scale == 1
    controls._last_frame -= 0.016
    controls._apply_pending()
    assert 1 < controls.scale < 1.3
    assert not calls
    before = controls.scale
    controls._last_frame -= 0.016
    controls._apply_pending()
    assert before < controls.scale < 1.3
    settle(controls)
    assert controls.scale == 1.3 and calls == [True]
    controls.request_scale(0.8)
    settle(controls)
    assert controls.scale == 0.8


def test_touchpad_pixel_delta_takes_precedence(window):
    widget, controls = window.avatar_label, window._controls
    point = widget.rect().center()
    event = QWheelEvent(QPointF(point), QPointF(widget.mapToGlobal(point)), QPoint(0, 1), QPoint(0, 120),
                        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                        Qt.ScrollPhase.ScrollUpdate, False)
    assert controls.eventFilter(widget, event)
    assert controls._target_scale == pytest.approx(1.1 ** (1 / 60))


def test_hover_palette_fades_and_does_not_cover_bubble(window):
    toolbar = window._pet_toolbar
    toolbar._poll.stop()
    toolbar.update_proximity(window.avatar_label.mapToGlobal(QPoint(10, 10)), 10)
    assert toolbar._revealed and toolbar.isVisible()
    assert toolbar.geometry().bottom() < window.avatar_label.geometry().bottom()
    far = QPoint(-10000, -10000)
    toolbar.update_proximity(far, 10.2)
    assert toolbar._revealed
    toolbar.update_proximity(far, 10.5)
    assert not toolbar._revealed
    toolbar._fade.setCurrentTime(toolbar._fade.duration())
    assert not toolbar.isVisible()
    assert toolbar.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)


def test_hover_buttons_are_self_only_and_preserve_draft(window):
    toolbar = window._pet_toolbar
    toolbar._poll.stop()
    window.input_bar.input_box.setText("还没写完")
    toolbar.buttons["quiet"].click()
    assert not window._quiet_mode and not toolbar.buttons["quiet"].isChecked()
    window._set_quiet(True)
    assert toolbar.buttons["quiet"].isChecked()
    toolbar.buttons["smaller"].click()
    settle(window._controls)
    assert window._controls.scale < 1
    toolbar.buttons["reset"].click()
    settle(window._controls)
    assert window._controls.scale == 1
    assert window.input_bar.text() == "还没写完"
    for button in toolbar.buttons.values():
        assert button.toolTip() and not button.icon().isNull()
