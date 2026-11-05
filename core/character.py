"""Small, source-linked character guide; available before embedding warmup."""
import json
import logging
from functools import lru_cache
from pathlib import Path

CHARACTER_DIR = Path(__file__).resolve().parents[1] / "data" / "character"


class CharacterGuide:
    def __init__(self, directory=CHARACTER_DIR):
        self.profile, self.lines = {}, []
        try:
            self.profile = json.loads((directory / "persona.json").read_text(encoding="utf-8"))
            with (directory / "lines.jsonl").open(encoding="utf-8") as stream:
                self.lines = [json.loads(line) for line in stream if line.strip()]
        except (OSError, ValueError):
            logging.warning("Character guide unavailable; base persona remains active")

    def identity(self):
        # Full example dialogues remain an editable review dataset. Small models
        # confused them with live events, so generation receives the derived behavior.
        return "【相处方式】\n" + "\n".join(self.profile.get("principles", []))

    def context(self, text):
        scenes = self.profile.get("scenes", [])
        ranked = [(sum(word in text for word in scene["triggers"]), scene) for scene in scenes]
        score, scene = max(ranked, key=lambda pair: pair[0], default=(0, {}))
        if not score:
            return ""
        return "【本轮相处方式，话题以当前输入为准】\n" + scene["guidance"]


@lru_cache(maxsize=1)
def get_character_guide():
    return CharacterGuide()
