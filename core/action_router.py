"""Explicit desktop requests, independent of character dialogue and its wording."""
from dataclasses import dataclass
import re
from urllib.parse import urlsplit


APP_NAMES = {
    "记事本": "notepad", "notepad": "notepad", "计算器": "calc", "calc": "calc",
    "画图": "mspaint", "mspaint": "mspaint", "浏览器": "browser", "默认浏览器": "browser",
    "谷歌浏览器": "chrome", "chrome": "chrome", "edge": "msedge", "微软浏览器": "msedge",
}
ENGINES = {"谷歌": "google", "google": "google", "百度": "baidu", "baidu": "baidu",
           "必应": "bing", "bing": "bing", "维基百科": "wikipedia", "维基": "wikipedia", "wikipedia": "wikipedia"}


@dataclass
class DirectRequest:
    action: dict = None
    clarification: str = ""


def _command_text(text):
    text = text.strip().strip("。！!？?～~ ")
    text = re.sub(r"^(?:小乐|蕾缪乐)[，,\s]*", "", text)
    for _ in range(3):
        text = re.sub(r"^(?:你)?(?:能不能|可不可以|可以|能)?(?:请|麻烦你|帮我|给我|替我)\s*", "", text)
    text = re.sub(r"^(?:你)?(?:现在|赶快|快点|快|先|去)\s*", "", text)
    text = re.sub(r"^你(?=打开|启动|运行|把|搜索|搜)", "", text)
    return text


def direct_request(text, previous=None):
    """Full matches only. Never infer a target from the assistant's promises."""
    command = _command_text(text)
    reversed_open = re.fullmatch(r"把(.+?)(?:给我)?(?:打开|启动)(?:吧|呀|啊)?", command)
    if reversed_open and reversed_open[1].strip().lower() in APP_NAMES:
        return DirectRequest({"type": "open", "target": APP_NAMES[reversed_open[1].strip().lower()]})
    match = re.fullmatch(r"(?:打开|启动|运行)(?:一下)?\s*(.+?)(?:吧|呀|啊|啦|好吗|可以吗|吗)?", command, re.I)
    if match:
        target = match[1].strip()
        app = APP_NAMES.get(target.lower())
        if app:
            return DirectRequest({"type": "open", "target": app})
        if re.fullmatch(r"https?://[^\s，。；;\"<>]+", target):
            return DirectRequest({"type": "open", "target": target})
    if re.fullmatch(r"(?:打开|启动)(?:呀|啊|吧|啦|它|一下|这个|那个)*", command):
        if previous and previous.get("type") == "open":
            return DirectRequest(dict(previous))
        return DirectRequest(clarification="要打开哪个应用或网址？我还没执行，得先确定目标。")
    # Search query is literal user text. Composite commands remain with the planner.
    match = re.fullmatch(r"(?:(?:在|去|用)?(谷歌|google|百度|baidu|必应|bing|维基百科|维基|wikipedia)(?:上)?)?"
                         r"(?:搜索|搜一下|搜搜|搜)\s*(.+)", command, re.I)
    if match:
        query = match[2].strip()
        if re.search(r"(?:然后|并且|并|再|顺便).{0,8}(?:打开|点击|输入|下载)|打开第|点开第", query):
            return None
        query = query.strip("\"“”‘’'")
        if query:
            return DirectRequest({"type": "search", "query": query,
                                  "engine": ENGINES.get((match[1] or "google").lower(), "google")})
    return None


def validate_action(action):
    if not isinstance(action, dict):
        raise ValueError("操作指令不是对象")
    kind = action.get("type")
    if not isinstance(kind, str) or kind.lower() not in {"open", "search", "click", "type", "hotkey", "scroll"}:
        raise ValueError("操作类型缺失或不支持")
    kind = kind.lower()
    result = dict(action, type=kind)
    required = {"open": "target", "search": "query", "type": "text"}.get(kind)
    if required and (not isinstance(action.get(required), str) or not action[required].strip()):
        raise ValueError("操作缺少参数：" + required)
    if kind == "open" and "://" in action["target"]:
        url = urlsplit(action["target"])
        if url.scheme not in {"http", "https"} or not url.hostname:
            raise ValueError("只允许 HTTP/HTTPS 网页")
    if kind == "search":
        engine = action.get("engine", "google")
        if not isinstance(engine, str) or engine.lower() not in set(ENGINES.values()):
            raise ValueError("不支持的搜索引擎")
        result["engine"] = engine.lower()
    if kind == "click":
        import math
        if any(isinstance(action.get(k), bool) or not isinstance(action.get(k), (int, float))
               or not math.isfinite(action[k]) for k in ("x", "y")):
            raise ValueError("点击坐标无效")
    if kind == "hotkey":
        keys = action.get("keys")
        if not isinstance(keys, list) or not keys or any(not isinstance(k, str) or not k for k in keys):
            raise ValueError("快捷键参数无效")
    if kind == "scroll" and action.get("direction", "down") not in {"up", "down"}:
        raise ValueError("滚动方向无效")
    return result
