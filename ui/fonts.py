"""Register a Chinese system font explicitly, including in offscreen diagnostic mode."""
import os
from pathlib import Path
from PyQt6.QtGui import QFont, QFontDatabase


def configure_fonts(app):
    font = Path(os.getenv("WINDIR", "C:/Windows")) / "Fonts" / "msyh.ttc"
    if font.exists():
        font_id = QFontDatabase.addApplicationFont(str(font))
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            app.setFont(QFont(families[0], 10))
            return families[0]
    return app.font().family()
