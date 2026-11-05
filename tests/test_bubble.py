from PyQt6.QtWidgets import QApplication
from ui.widgets import AKBubble
from ui.window import CompanionWindow


def test_bubble_shrinks_and_wraps_with_text():
    app = QApplication.instance() or QApplication([])
    bubble = AKBubble()
    bubble.set_width_limit(300)
    bubble.setText("好呀！")
    short = bubble.size()
    bubble.setText("今天先聊聊天吧，刚才那个话题我还没听完。" * 4)
    assert bubble.width() <= 300
    assert bubble.height() > short.height()
    assert bubble.width() > short.width()
    bubble.setText("嗯。")
    assert bubble.height() == short.height()
    bubble.close()


def test_typewriter_reserves_sentence_size():
    app = QApplication.instance() or QApplication([])
    bubble = AKBubble()
    text = "这句比较长，需要换行显示，但打字过程中尺寸不应该反复跳动。" * 2
    bubble.setText(text[:2], sizing_text=text)
    size = bubble.size()
    for end in (10, 30, len(text)):
        bubble.setText(text[:end], sizing_text=text)
        assert bubble.size() == size
    bubble.close()


def test_bubble_top_stays_under_avatar_and_bottom_shrinks_upward():
    app = QApplication.instance() or QApplication([])
    window = CompanionWindow(initialize_sensors=False)
    window.show()
    window._show_bubble("好呀！")
    app.processEvents()
    avatar, input_bar = window.avatar_label.geometry(), window.input_bar.geometry()
    short = window.bubble.geometry()
    assert short.top() == avatar.bottom() + 1
    assert short.left() < avatar.left() and short.right() > avatar.right()
    assert short.height() >= 64
    window._show_bubble("我想把这个问题说清楚，但也不需要塞进一个固定大小的空盒子里。" * 3)
    app.processEvents()
    assert window.avatar_label.geometry() == avatar
    assert window.bubble.y() == short.top()
    assert window.input_bar.y() > input_bar.y()
    assert window.bubble.height() <= 180
    window._show_bubble("嗯。")
    app.processEvents()
    assert window.bubble.geometry() == short
    assert window.input_bar.geometry() == input_bar
    window.close()


def test_pages_respect_size_and_keep_newlines_emoji_and_long_words():
    app = QApplication.instance() or QApplication([])
    bubble = AKBubble()
    bubble.set_maximum_extent(240, 100)
    text = ("中文段落。\n" + "verylongword" * 20 + "\n" + "\U0001f469\u200d\U0001f4bb e\u0301 " * 20) * 2
    rest, pages = text, []
    while rest:
        page, rest = bubble.take_page(rest)
        assert page and bubble.fits_text(page)
        assert not page.endswith("\u200d")
        assert not rest.startswith(("\u200d", "\u0301"))
        bubble.setText(page)
        bubble.show()
        app.processEvents()
        assert bubble.label.text() == page
        assert bubble.width() <= 240 and bubble.height() <= 100
        assert bubble.label.height() >= bubble.label.heightForWidth(bubble.label.width())
        pages.append(page)
    assert "".join(pages) == text
    assert len(pages) > 2
    bubble.close()


def test_full_page_has_room_for_actual_qlabel_line_spacing():
    app = QApplication.instance() or QApplication([])
    window = CompanionWindow(initialize_sensors=False, use_memory=False)
    window.bubble.set_maximum_extent(316, 180)
    text = "这是一段用于检查跨页的长文本。先完整显示这一页，再留出阅读时间，之后才切换下一页。" * 12
    head, _ = window.bubble.take_page(text)
    window._show_bubble(head)
    window.show()
    app.processEvents()
    label = window.bubble.label
    assert label.height() >= label.heightForWidth(label.width())
    window.close()
