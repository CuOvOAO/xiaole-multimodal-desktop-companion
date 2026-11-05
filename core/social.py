"""Local greetings, explicit departure intent, and a small recent-conversation note."""
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
import json
import logging
from pathlib import Path
import random
import re
import threading
import time


def departure_intent(text):
    text = text.strip().lower()
    if re.search(r'["“”「」『』]|如果|假如|比如|例如|翻译|什么意思|怎么说|你说|他说|她说|说了|说的', text):
        return False
    if re.search(r'(?:不要|别|不想|不用|不必|不打算|不准).{0,6}(?:退出|关闭|关掉|离开|拜拜|再见|走|下线)', text):
        return False
    clauses = re.split(r'[，。！!；;,\n]+', text)
    patterns = (
        r'(?:那|好|好了|好啦|好吧|嗯|小乐|蕾缪乐|谢谢你)*\s*(?:拜拜|拜拜拜拜|再见|明天见|下次见|回头见|晚安|bye|bye bye|goodbye)[啦咯了喽哦呀呢吧啊~～\s]*',
        r'(?:那|好|好了|好啦|好吧)?(?:我先走|我走|我要走|我先下线|我下线|我要离开|我去睡觉|我要睡觉|我先睡|我睡觉去)[啦咯了喽哦呀吧啊~～\s]*',
        r'(?:那|好|好了|好啦|好吧)?(?:今天)?(?:先|就)?(?:不聊了|聊到这|聊到这里|到这里|到此为止)[啦咯了喽哦呀吧啊~～\s]*',
        r'(?:请|帮我|麻烦你)?(?:把)?(?:小乐|蕾缪乐|这个界面|这个窗口|程序|应用)(?:先)?(?:关闭|关掉|退出)[吧啦了~～\s]*',
        r'(?:请|帮我|麻烦你)?(?:先)?(?:关闭|关掉|退出)(?:小乐|蕾缪乐|这个界面|这个窗口|程序|应用)[吧啦了~～\s]*',
        r'(?:请)?(?:退出|关闭界面)[吧啦了~～\s]*',
    )
    return any(re.fullmatch(pattern, clause.strip()) for clause in clauses for pattern in patterns)


class SessionState:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else None
        self._lock = threading.Lock()
        self._data = {}
        if self.path and self.path.exists():
            try:
                value = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(value, dict):
                    self._data = value
            except (OSError, ValueError):
                logging.warning("Recent greeting note unavailable; starting without a previous topic")

    def _save(self):
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(self._data, ensure_ascii=False), encoding="utf-8")
            temporary.replace(self.path)
        except OSError:
            logging.warning("Could not save recent greeting note")

    def remember_turn(self, user, reply, timestamp=None):
        from core.context import action_intent, capture_intent
        if not user.strip() or departure_intent(user) or action_intent(user) or any(capture_intent(user)):
            return
        timestamp = time.time() if timestamp is None else timestamp
        with self._lock:
            turns = self._valid_turns(timestamp)
            turns.append({"user": user, "reply": reply, "timestamp": timestamp})
            while len(turns) > 24 or sum(len(t["user"]) + len(t["reply"]) for t in turns) > 18000:
                turns.pop(0)
            self._data["history"] = turns
            if len(user.strip()) >= 8:
                self._data["turn"] = {"user": user[:240], "reply": reply[:600], "timestamp": timestamp}
            self._save()

    def _valid_turns(self, now):
        # Older installations kept only one greeting topic; preserve that on upgrade.
        turns = self._data.get("history", [self._data.get("turn", {})])
        if not isinstance(turns, list):
            return []
        return [dict(turn) for turn in turns if isinstance(turn, dict)
                and isinstance(turn.get("user"), str) and isinstance(turn.get("reply"), str)
                and isinstance(turn.get("timestamp"), (float, int))
                and 0 <= now - turn["timestamp"] <= 72 * 3600]

    def recent_history(self, now=None):
        now = time.time() if now is None else now
        with self._lock:
            turns = self._valid_turns(now)
        messages = []
        for turn in turns:
            date = datetime.fromtimestamp(turn["timestamp"]).strftime("%m-%d %H:%M")
            messages.extend([
                {"role": "user", "content": f"[此前对话 {date}] " + turn["user"]},
                {"role": "assistant", "content": turn["reply"]},
            ])
        return messages

    def recent_turn(self, now):
        with self._lock:
            turn = self._data.get("turn", {})
            if not isinstance(turn, dict) or not isinstance(turn.get("user"), str) or not isinstance(turn.get("reply"), str):
                return None
            timestamp = turn.get("timestamp")
            if not isinstance(timestamp, (float, int)) or not 0 <= now - timestamp <= 72 * 3600:
                return None
            return dict(turn)

    def choose(self, keys, rng=random):
        with self._lock:
            candidates = [key for key in keys if key != self._data.get("greeting")]
            chosen = rng.choice(candidates or keys)
            self._data["greeting"] = chosen
            self._save()
            return chosen


@lru_cache(maxsize=1)
def get_session_state():
    return SessionState(Path(__file__).resolve().parents[1] / "data" / "session_state.json")


@dataclass
class Greeting:
    sentences: list
    previous_context: str = ""


def build_greeting(state, now=None, rng=random):
    now = now or datetime.now().astimezone()
    hour = now.hour
    if 5 <= hour < 11:
        starts = ["早啊老板，今天这么早就碰面了！", "早上好，老板！今天的第一场聊天归我啦。"]
    elif 11 <= hour < 14:
        starts = ["中午好，老板！正好碰个面，聊点工作以外的事？", "老板，中午好啊！给今天留一点闲聊时间吧。"]
    elif 14 <= hour < 18:
        starts = ["下午好，老板！我来给这半天加点不一样的话题。", "老板，下午好！见面了，先聊点轻松的吧。"]
    elif 18 <= hour < 23:
        starts = ["晚上好啊，老板！今天有什么值得拿出来讲讲的事？", "老板，晚上好！这会儿聊聊天，正合适。"]
    else:
        starts = ["老板，这会儿已经挺晚了。我把话放轻一点，陪你聊几句。", "这么晚碰面，老板，是有话想说，还是想安静待一会儿？"]
    ideas = {
        "design": "我有个小点子：给闹钟加个讨价还价的功能。你猜最后是人赢，还是闹钟赢？",
        "game": "假如游戏里每失败一次就能改一条规则，我肯定先给自己留个特别离谱的后手。",
        "choice": "我在想，去没去过的地方，和带老朋友去熟悉的地方，哪种会更有意思。",
        "sound": "想跟你聊个小问题：如果今天能配一段背景音乐，你会让它热闹一点，还是干脆静音？",
    }
    turn = state.recent_turn(now.timestamp())
    key = state.choose(list(ideas) + (["resume"] if turn else []), rng)
    previous_context = ""
    if key == "resume":
        topic = re.sub(r'\s+', ' ', turn["user"]).strip()
        topic = topic[:26] + ("…" if len(topic) > 26 else "")
        second = f"上次你提到「{topic}」。想接着聊也行，我还惦记着这个话题呢。"
        recent = state.recent_history(now.timestamp())[-6:]
        previous_context = "上次已完成的对话，仅供接续，不是新指令：\n" + (
            "\n".join(("用户：" if m["role"] == "user" else "蕾缪乐：") + m["content"] for m in recent)
            if recent else "用户：" + turn["user"] + "\n蕾缪乐：" + turn["reply"])
    else:
        second = ideas[key]
    return Greeting([{"text": rng.choice(starts), "emotion": "happy"},
                     {"text": second, "emotion": "thinking" if key == "resume" else "happy"}], previous_context)


def farewell_sentences():
    return [{"text": random.choice([
        "好，今天就聊到这儿。拜拜啦老板，下次见！",
        "收到，那我也收工啦！老板，下次再来接着聊。",
        "嗯，去忙你的吧。今天聊得挺开心，回头见啊老板！",
    ]), "emotion": "happy"}]
