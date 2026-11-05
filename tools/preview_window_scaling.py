"""Offscreen zoom QA: synthetic screen sizes, no models, sensors or OS actions."""
import os
from pathlib import Path
import sys
import traceback
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QRect
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from ui.fonts import configure_fonts
from ui.window import CompanionWindow


def main():
    errors = []
    def report_error(*args):
        errors.append(args)
        traceback.print_exception(*args, file=sys.stdout)
    sys.excepthook = report_error
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    configure_fonts(app)
    output = ROOT / "data" / "logs"
    output.mkdir(parents=True, exist_ok=True)
    for width, height in ((800, 600), (1920, 1080), (3840, 2160)):
        for scale in (0.7, 1.0, 1.75):
            window = CompanionWindow(initialize_sensors=False, use_memory=False)
            screen = QRect(0, 0, width, height)
            window._controls.screen_rect = lambda *_: screen
            window._controls.set_scale(scale)
            window.show()
            window._pet_toolbar._poll.stop()
            for label, text in (("short", "在呢，老板。"),
                                ("page", "今天先不急，我在这儿陪着你。等你把手里的事情做完，我们再接着聊刚才那个话题。" * 12)):
                page, _ = window.bubble.take_page(text)
                window._show_bubble(page)
                app.processEvents()
                avatar = window.avatar_label.geometry()
                bubble = window.bubble.geometry()
                assert bubble.top() == avatar.bottom() + 1
                assert bubble.left() < avatar.left() and bubble.right() > avatar.right()
                assert window.input_bar.y() > bubble.bottom()
                assert window.input_bar.geometry().bottom() < window.height()
                assert screen.contains(window.geometry())
                text_label = window.bubble.label
                assert text_label.height() >= text_label.heightForWidth(text_label.width())
                snapshot = window.grab()
                image = snapshot.toImage()
                pixels = sum(image.pixelColor(x, y).alpha() > 0
                             for x in range(avatar.left(), avatar.right(), 10)
                             for y in range(avatar.top(), avatar.bottom(), 10))
                assert pixels > 20, "Blank avatar"
                path = output / ("zoom-%sx%s-%s-%s.png" % (width, height, scale, label))
                assert snapshot.save(str(path))
            window._pet_toolbar.reveal(True)
            QTest.qWait(200)
            assert window._pet_toolbar.geometry().bottom() < window.bubble.y()
            assert window.grab().save(str(output / ("hover-%sx%s-%s.png" % (width, height, scale))))
            print("screen=%sx%s request=%.2f actual=%.2f size=%sx%s" % (
                width, height, scale, window._controls.scale, window.width(), window.height()))
            window.close()
    window = CompanionWindow(initialize_sensors=False, use_memory=False)
    window._controls.screen_rect = lambda *_: QRect(0, 0, 3840, 2160)
    window._controls.set_scale(0.7)
    window.show()
    window._pet_toolbar._poll.stop()
    window._show_bubble("缩放过程中，文字和立绘一起平滑变化。")
    frame_times = []
    render = window._controls._render_scale
    def timed_render(*args):
        started = time.perf_counter()
        render(*args)
        frame_times.append((time.perf_counter() - started) * 1000)
    window._controls._render_scale = timed_render
    window._controls.request_scale(1.5)
    sizes = []
    for index in range(40):
        QTest.qWait(16)
        sizes.append(window.width())
        if index in (0, 3, 8, 20):
            assert window.grab().save(str(output / ("zoom-motion-%s.png" % index)))
    assert len(set(sizes)) >= 8, "Scale jumped instead of interpolating"
    assert all(a <= b for a, b in zip(sizes, sizes[1:]))
    assert not window._controls._apply_timer.isActive()
    print("animated zoom: %s distinct widths across %s samples" % (len(set(sizes)), len(sizes)))
    print("zoom layout work: mean %.1f ms, max %.1f ms" % (sum(frame_times) / len(frame_times), max(frame_times)))
    window.close()
    app.processEvents()
    assert not errors, "Unhandled Qt callback errors"


if __name__ == "__main__":
    main()
