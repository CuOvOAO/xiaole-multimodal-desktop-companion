"""Input provenance and short-lived visual context; no Qt or network dependencies."""
from dataclasses import dataclass, field
import re
import threading
import time


@dataclass
class Interaction:
    text: str
    source: str = "text"
    screen_b64: str = ""
    camera_b64: str = ""
    notes: str = ""
    created_at: float = field(default_factory=time.monotonic)

    def content(self):
        parts = []
        for label, picture in (("屏幕截图", self.screen_b64), ("摄像头画面", self.camera_b64)):
            if picture:
                parts.extend([
                    {"type": "text", "text": f"[本轮{label}]"},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{picture}"}},
                ])
        origin = "语音转写" if self.source in {"voice", "asr"} else "文字输入"
        parts.append({"type": "text", "text": f"[{origin}] {self.text}\n{self.notes}".strip()})
        return parts if self.screen_b64 or self.camera_b64 else parts[-1]["text"]


def capture_intent(text, recent_visual=False):
    camera = bool(re.search(r"看看我|看一下我|我的表情|摄像头|拍我|我长什么|看我现在", text))
    screen = bool(re.search(r"屏幕|截图|这个界面|这个窗口|我在做什么|看下桌面", text))
    # Follow-up questions keep the last visual channel briefly; generic '我现在' does not open a camera.
    followup = bool(re.search(r"那张|图里|画面里|那是什么|这是什么|这个呢|刚才(?:那张|那个画面|屏幕|摄像头)", text))
    if followup and recent_visual and not screen and not camera:
        camera = recent_visual in {"camera", "both"}
        screen = recent_visual is True or recent_visual in {"screen", "both"}
    if re.search(r"不要.{0,3}(看我|摄像头|拍我)|关闭摄像头", text):
        camera = False
    if re.search(r"不要.{0,3}(看屏幕|截图)|关闭屏幕感知", text):
        screen = False
    return screen, camera


def reply_style(text):
    """Allocate a ceiling, not a target length; listening is not forced brevity."""
    brief = re.search(r"(?:只用|只说|就说|用)一句话|简短(?:点|些|一点)?|短一点|少说一点|长话短说", text)
    expanded = re.search(r"多说|多聊|展开|详细|说说理由|为什么|怎么看|怎么想|解释|步骤|怎么(?:做|办|用|实现|解决)", text)
    if brief and not re.search(r"(?:别|不要|不用)[^，。！？,!?;；\n]{0,3}(?:只用|只说|用一句|一句话|简短|少说)", text):
        return "本轮要求简短：直接回答刚才的话题，不复读这条篇幅指令，不额外展开。", 220
    if re.fullmatch(r"(?:你好|嗨|早安|晚安|谢谢|好的|好呀|嗯|收到)[！!。 .～~]*", text.strip()):
        return "简单招呼或确认，自然接一句即可，不强行延伸话题。", 220
    if re.search(r"(?:别|不(?:要|用)).{0,6}(?:建议|方案|清单)|就聊.{0,8}(?:感觉|心情)", text):
        return ("本轮是聊天而非求方案：用这件事的具体细节展开为什么会难受或矛盾，"
                "可以有自己的看法，不替对方诊断。不提供解决步骤，不承诺未来一定好转，"
                "不拿普遍道理或泛泛安慰收尾。"), 700
    if re.search(r"^(?:更正|改成|改为|我改主意|我说的是)|按.{0,8}(?:规则|约定)", text) and not expanded:
        return "这是纠正或确认约定：回应本轮具体变更，保留前面未被修改的条件；不要另加规则、玩笑或建议。", 450
    if expanded:
        return "本轮值得展开：把自己的判断和具体理由聊清楚，必要时说取舍或可能性；不只复述，不列空泛结论。没有要求建议就不强行开药方。", 1000
    return "按内容自然回应，可以把一个意思聊成完整段落。比复述多走一步：说出自己的观察、理由或具体想法；不强行给建议、反问或收尾。", 700


def action_intent(text):
    """Conservative command gate; ambient observations never authorize actions."""
    if re.search(r"(?:不要|别|不许).{0,8}(?:打开|搜索|操作|点击|输入|滚动)", text):
        return False
    from core.action_router import direct_request
    if direct_request(text) is not None:
        return True
    return bool(re.search(r"(?:帮我|请|去|给我).{0,12}(?:搜|查|打开|点|输入|滚)|^(?:打开|搜索|搜一下|搜搜|查一下|点击|输入|滚动)|(?:在|去).{0,8}(?:维基|百度|谷歌).{0,4}搜", text))


def grounding_guidance(text):
    """Factual help needs source boundaries, not a second model/rewriting pass."""
    if re.search(r"别.{0,5}(?:建议|解题)|不(?:看|聊|讨论).{0,5}(?:论文|公式)|就聊.{0,8}(?:感觉|心情)", text):
        return ""
    if re.search(r"论文|公式|推导|证明|文献|数学|代码|报错|原理|算法|看懂|能看.{0,4}内容", text):
        return ("本轮是理解材料或核实能力：区分收到的原文/画面与用户的口头描述。"
                "材料未提供时直接说明还没看到，并只问必要的信息；已有材料就回答具体内容。"
                "不把读懂文字等同于验证结论，不无依据自夸或自贬，不插入角色爱好和无关比喻。")
    return ""


def memory_budget(text, default):
    return max(default, 0.8) if re.search(r"记得|上次|之前|曾经|姐姐|拉特兰|萨科塔|设定", text) else default


def character_fact_intent(text):
    return bool(re.search(r"姐姐|蕾缪安|拉特兰|萨科塔|企鹅物流|莫斯提马|德克萨斯|铳|光环|设定|档案|毕业|过去|以前的你|你的经历|生日|身高|故乡|家乡|信仰", text))


def estimate_tokens(text):
    """Conservative CJK/ASCII estimate, avoiding a heavyweight tokenizer at startup."""
    non_ascii = sum(ord(char) > 127 for char in text)
    return int(non_ascii * 1.3 + (len(text) - non_ascii) / 3) + 8


def fit_history(history, budget):
    result = list(history)
    while result and sum(estimate_tokens(str(message.get("content", ""))) for message in result) > budget:
        del result[:2]  # Never keep an assistant answer without its paired user input.
    return result


class ObservationStore:
    """Only text observations are shared across modalities, with an explicit expiry."""
    def __init__(self, ttl=45.0):
        self.ttl = ttl
        self._lock = threading.Lock()
        self._latest = {}

    def update(self, text, source="screen"):
        with self._lock:
            self._latest[source] = (time.monotonic(), str(text)[:400], source)

    def context(self):
        with self._lock:
            values = list(self._latest.values())
        parts = []
        for timestamp, text, source in sorted(values, reverse=True)[:3]:
            age = time.monotonic() - timestamp
            if age <= self.ttl:
                parts.append(f"[约{int(age)}秒前的{source}，仅供接续话题，并非当前画面] {text}")
        return "\n".join(parts)
