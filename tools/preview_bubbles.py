"""Offscreen layout preview without models, sensors or desktop actions."""
import os
from pathlib import Path
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
from ui.fonts import configure_fonts
from ui.window import CompanionWindow


def main():
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    configure_fonts(app)
    output = ROOT / "data" / "logs"
    output.mkdir(parents=True, exist_ok=True)
    for width in (560, 440, 340):
        class PreviewWindow(CompanionWindow):
            WIN_W = width
        window = PreviewWindow(initialize_sensors=False, use_memory=False)
        window.show()
        for name, text in (("short", "好呀！"), ("long", "会惦记没走过的那条路啊。不过要拿现在认识的人去换，我又不肯了。是不是有点贪心？" * 2)):
            window._show_bubble(text)
            QTest.qWait(100)
            snapshot = window.grab()
            snapshot.save(str(output / ("bubble-%s-%s.png" % (width, name))))
            rect = window.avatar_label.geometry()
            image = snapshot.toImage()
            visible_pixels = sum(image.pixelColor(x, y).alpha() > 0
                                 for x in range(rect.left(), rect.right(), 10)
                                 for y in range(rect.top(), rect.bottom(), 10))
            assert visible_pixels > 20, "Avatar disappeared during bubble resizing"
            print(width, name, window.bubble.size().width(), window.bubble.size().height())
        player = window._sentence_player
        player.play([{"text": text, "emotion": "neutral"} for text in (
            "这一页可以接着放下一句话，不用说一句就把前面的清掉。",
            "我还想把理由讲完。只要气泡放得下，前面的内容就会留着。",
            "超出最大尺寸后再换页，输入框仍然在下方。",
        )])
        for _ in range(12):
            if player._type_timer.isActive():
                player._index = len(player._current_text)
                player._type_next_char()
            elif player._queue:
                player._play_next()
            else:
                break
        QTest.qWait(30)
        assert "这一页" in window.bubble.label.text()
        assert "输入框" in window.bubble.label.text()
        window.grab().save(str(output / ("bubble-%s-merged.png" % width)))
        anchor = window.avatar_label.geometry()
        text = "这是一段用于检查跨页的长文本。先完整显示这一页，再留出阅读时间，之后才切换下一页。" * 12
        player.play([{"text": text, "emotion": "neutral"}])
        pages = []
        for _ in range(20):
            player._index = len(player._current_text)
            player._type_next_char()
            QTest.qWait(30)
            pages.append(window.bubble.label.text())
            bubble_rect = window.bubble.geometry()
            assert window.avatar_label.geometry() == anchor
            assert bubble_rect.top() == anchor.bottom() + 1
            assert bubble_rect.left() < anchor.left() and bubble_rect.right() > anchor.right()
            assert window.input_bar.y() > bubble_rect.bottom()
            assert window.input_bar.geometry().bottom() < window.height()
            assert window.bubble.fits_text(pages[-1])
            label = window.bubble.label
            assert label.height() >= label.heightForWidth(label.width())
            window.grab().save(str(output / ("bubble-%s-page-%s.png" % (width, len(pages)))))
            if not player._queue:
                break
            player._play_next()
            if player._awaiting_page:
                player._play_next()
        assert "".join(pages) == text
        assert len(pages) >= 2
        print(width, "pages", len(pages), "max height", window.bubble._height_limit)
        window.close()
    app.processEvents()


if __name__ == "__main__":
    main()
