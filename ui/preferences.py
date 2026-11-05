"""Small local presentation preferences, separate from conversation memory."""
import json
import logging
import math
from pathlib import Path


class WindowPreferences:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else None
        self.scale = 1.0
        self.quiet = True
        self.position = None
        if not self.path:
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return
            scale = data.get("scale")
            if isinstance(scale, (int, float)) and not isinstance(scale, bool) and math.isfinite(scale):
                self.scale = max(0.7, min(1.75, scale))
            if isinstance(data.get("quiet"), bool):
                self.quiet = data["quiet"]
            position = data.get("position")
            if isinstance(position, list) and len(position) == 2 and all(
                isinstance(n, int) and not isinstance(n, bool) and abs(n) < 100000 for n in position
            ):
                self.position = position
        except (OSError, ValueError):
            logging.info("Window preferences unavailable; using defaults")

    def save(self):
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps({"scale": self.scale, "quiet": self.quiet,
                                              "position": self.position}), encoding="utf-8")
            temporary.replace(self.path)
        except OSError:
            logging.warning("Could not save window preferences")
