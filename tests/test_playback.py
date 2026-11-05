from PyQt6.QtWidgets import QApplication, QWidget
from types import SimpleNamespace
from ui.playback import SentencePlayer
from ui.widgets import AKBubble


def make_player():
    app = QApplication.instance() or QApplication([])
    window = QWidget()
    window.unlocked = 0
    window.shown = []
    window.actions = []
    window.avatar_mgr = SimpleNamespace(set_emotion=lambda emotion: None)
    window.bubble = AKBubble(window)
    def show(text, full_text=None):
        window.shown.append(text)
        window.bubble.setText(text, sizing_text=full_text)
    window._show_bubble = show
    window._unlock = lambda: setattr(window, "unlocked", window.unlocked + 1)
    window._execute_action_async = window.actions.append
    return app, window, SentencePlayer(window)


def test_new_stream_does_not_inherit_done_state():
    app, window, player = make_player()
    player._stream_done = True
    player.begin()
    player.enqueue("hello", "neutral")
    player._type_next_char()
    player._type_next_char()
    player._type_next_char()
    player._pause_timer.stop()
    player._play_next()
    assert window.unlocked == 0
    player.mark_stream_done()
    assert window.unlocked == 1
    player.stop()


def finish_typing(player):
    for _ in range(2000):
        if not player._type_timer.isActive():
            return
        player._type_next_char()
    raise AssertionError("Typewriter failed to finish")


def test_sentences_append_to_current_page_instead_of_replacing_it():
    app, window, player = make_player()
    player.enqueue("第一句话。", "neutral")
    player.enqueue("这个理由也很重要。", "thinking")
    player.mark_stream_done()
    finish_typing(player)
    player._play_next()
    finish_typing(player)
    assert window.bubble.label.text() == "第一句话。\n这个理由也很重要。"
    assert window.unlocked == 1
    player.stop()


def test_long_sentence_pages_without_losing_text_or_repeating_action():
    app, window, player = make_player()
    window.bubble.set_maximum_extent(240, 90)
    text = "我们把这个意思完整说出来，不用每句就清空气泡。" * 18
    player.enqueue(text, "thinking", '{"type":"search","query":"test"}')
    player.mark_stream_done()
    pages = []
    for _ in range(100):
        finish_typing(player)
        pages.append(window.bubble.label.text())
        assert window.bubble.fits_text(pages[-1])
        if window.unlocked:
            break
        assert not window.actions
        player._play_next()
        assert player._awaiting_page
        assert player._pause_timer.isActive()
        player._play_next()  # Simulate reading timer timeout.
    assert "".join(pages) == text
    assert len(pages) > 1 and len(window.actions) == 1
    assert window.unlocked == 1
    player.stop()


def test_late_chunk_appends_and_completion_does_not_unlock_between_chunks():
    app, window, player = make_player()
    player.enqueue("先说清一点。", "neutral")
    finish_typing(player)
    assert window.unlocked == 0
    player.enqueue("再补充理由。", "neutral")
    finish_typing(player)
    assert window.bubble.label.text() == "先说清一点。\n再补充理由。"
    assert window.unlocked == 0
    player.mark_stream_done()
    assert window.unlocked == 1
    player.stop()


def test_preview_is_not_replayed_and_new_turn_clears_page():
    app, window, player = make_player()
    window._preview_text = "已经显示"
    player.enqueue("已经显示的内容。", "neutral")
    assert player._index == 4
    finish_typing(player)
    player.stop()
    player.enqueue("新的一轮。", "neutral")
    finish_typing(player)
    assert window.bubble.label.text() == "新的一轮。"
    player.stop()


def test_stop_during_page_reading_discards_remaining_action():
    app, window, player = make_player()
    window.bubble.set_maximum_extent(240, 80)
    player.enqueue("这是需要跨页才能讲完的一段话。" * 20, "thinking", '{"type":"open","target":"test"}')
    finish_typing(player)
    player._play_next()
    assert player._awaiting_page
    player.stop()
    assert not player._queue and not player._pause_timer.isActive()
    assert not player._page_text and not window.actions


def test_stop_clears_timers_queue_and_pending_action():
    app, window, player = make_player()
    player.enqueue("hello", "neutral", '{"type":"search","query":"test"}')
    player.stop()
    assert not player.is_playing()
    assert not player._type_timer.isActive()
    assert not player._pause_timer.isActive()
    assert not window.actions


def test_action_waits_until_sentence_is_displayed():
    app, window, player = make_player()
    player.enqueue("hello", "neutral", '{"type":"search","query":"test"}')
    assert not window.actions
    for _ in range(4):
        player._type_next_char()
    assert len(window.actions) == 1
    player.stop()


def test_final_sentence_unlocks_without_an_extra_reading_delay():
    app, window, player = make_player()
    player.enqueue("hello", "neutral")
    player.mark_stream_done()
    for _ in range(3):
        player._type_next_char()
    assert window.unlocked == 1
    assert not player._pause_timer.isActive()
    player.stop()
