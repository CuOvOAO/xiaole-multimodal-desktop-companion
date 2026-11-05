"""Local timing only: excludes dialogue text, images, keys and network error bodies."""
import json
import logging
import threading
import time
from pathlib import Path
from uuid import uuid4

_LOCK = threading.Lock()
PERF_PATH = Path(__file__).resolve().parents[1] / "data" / "logs" / "performance.jsonl"


class TurnMetrics:
    def __init__(self, source="text"):
        self.started = time.perf_counter()
        self.values = {"turn_id": uuid4().hex[:12], "source": source}

    def mark(self, name):
        self.values.setdefault(name + "_ms", round((time.perf_counter() - self.started) * 1000, 1))

    def save(self, status="ok"):
        self.mark("total")
        self.values["status"] = status
        if hasattr(self, "model"):
            self.values["model"] = self.model
        try:
            with _LOCK:
                PERF_PATH.parent.mkdir(parents=True, exist_ok=True)
                if PERF_PATH.exists() and PERF_PATH.stat().st_size > 2_000_000:
                    PERF_PATH.replace(PERF_PATH.with_suffix(".previous.jsonl"))
                with PERF_PATH.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(self.values, ensure_ascii=False) + "\n")
            logging.info("[Timing] %s", self.values)
        except OSError:
            logging.exception("Failed to write performance log")
