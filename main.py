"""Application entry point and diagnostic switches; optional modules never block startup."""
import argparse
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--no-asr", action="store_true")
    parser.add_argument("--no-proactive", action="store_true")
    parser.add_argument("--no-memory", action="store_true")
    parser.add_argument("--text-backend", choices=("auto", "cloud"), help="Override text model routing for this run")
    parser.add_argument("--smoke-test", action="store_true")
    args = parser.parse_args()
    if args.text_backend:
        os.environ["TEXT_BACKEND"] = args.text_backend
    if args.no_asr or args.smoke_test:
        os.environ["ASR_ENABLED"] = "0"
    if args.no_proactive or args.smoke_test:
        os.environ["PROACTIVE_ENABLED"] = "0"
    if args.smoke_test:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        os.environ["LOCAL_VISION_WARMUP"] = "0"

    folder = Path(__file__).resolve().parent / "data" / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    handlers = [logging.StreamHandler(sys.stdout)]
    if args.debug:
        handlers.append(RotatingFileHandler(folder / "app.log", maxBytes=2_000_000, backupCount=2, encoding="utf-8"))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=handlers)
    for name in ("httpx", "httpcore", "openai", "urllib3"):
        logging.getLogger(name).setLevel(logging.WARNING)

    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import QTimer
    from ui.window import CompanionWindow
    from ui.preferences import WindowPreferences

    app = QApplication(sys.argv[:1])
    from ui.fonts import configure_fonts
    logging.info("UI font: %s", configure_fonts(app))
    app.setQuitOnLastWindowClosed(True)
    win = CompanionWindow(initialize_client=not args.smoke_test,
                          use_memory=not (args.no_memory or args.smoke_test),
                          initialize_sensors=not args.smoke_test,
                          preferences=WindowPreferences(None if args.smoke_test else folder.parent / "window_preferences.json"))
    win.closed.connect(app.quit)
    app.aboutToQuit.connect(win.shutdown)
    win.show()
    QTimer.singleShot(400, win.start_greeting)
    if args.smoke_test:
        QTimer.singleShot(900, lambda: win.grab().save(str(folder / "smoke.png")))
        QTimer.singleShot(1300, win.close)
    logging.info("Window ready: python=%s ASR=%s proactive=%s", sys.executable,
                 os.environ.get("ASR_ENABLED", "1"), os.environ.get("PROACTIVE_ENABLED", "1"))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
