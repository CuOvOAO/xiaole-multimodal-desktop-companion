# core/desktop.py — 拟人化桌面控制
# 鼠标键盘动作与浏览器导航；动作授权/确认由 UI 层负责。
# 依赖：pyautogui、pyperclip
# 安装：pip install pyautogui pyperclip

from __future__ import annotations
import time
import random
import webbrowser
import os
from pathlib import Path
import subprocess
from urllib.parse import quote_plus

try:
    import pyautogui
    try:
        import ctypes
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.05  # 底层间隔尽量短，拟人延迟由我们自己控制
    _PYAUTOGUI_OK = True
except ImportError:
    _PYAUTOGUI_OK = False
    print("[Desktop] 警告：pyautogui 未安装。pip install pyautogui")

try:
    import pyperclip
    _CLIP_OK = True
except ImportError:
    _CLIP_OK = False
    print("[Desktop] 警告：pyperclip 未安装。pip install pyperclip")


# ── 搜索引擎映射 ─────────────────────────────────────────
SEARCH_ENGINES = {
    "google":    "https://www.google.com/search?q={}",
    "baidu":     "https://www.baidu.com/s?wd={}",
    "bing":      "https://www.bing.com/search?q={}",
    "wikipedia": "https://zh.wikipedia.org/wiki/Special:Search?search={}",
}


def _human_delay(lo: float = 0.08, hi: float = 0.25):
    """模拟真人操作间的随机停顿。"""
    time.sleep(random.uniform(lo, hi))


def _is_ascii(s: str) -> bool:
    """判断字符串是否全部是 ASCII（英文+符号），用于决定打字方式。"""
    try:
        s.encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


# ═══════════════════════════════════════════════════════════
#  HumanLikeController
# ═══════════════════════════════════════════════════════════
class HumanLikeController:
    """拟人化桌面控制器——所有操作模拟真人节奏。"""

    # ── 鼠标 ──────────────────────────────────────────────
    def move_to(self, x: int, y: int, duration: float = 0.5):
        if not _PYAUTOGUI_OK:
            return
        pyautogui.moveTo(x, y, duration=duration)

    def click(self, x: int, y: int, button: str = "left"):
        if not _PYAUTOGUI_OK:
            return
        pyautogui.moveTo(x, y, duration=random.uniform(0.3, 0.6))
        _human_delay(0.05, 0.15)
        pyautogui.click(button=button)

    def scroll(self, direction: str = "down", amount: int = 3):
        if not _PYAUTOGUI_OK:
            return
        clicks = amount if direction == "up" else -amount
        pyautogui.scroll(clicks)

    # ── 键盘 ──────────────────────────────────────────────
    def hotkey(self, *keys: str):
        if not _PYAUTOGUI_OK:
            return
        pyautogui.hotkey(*keys)

    def type_text(self, text: str, wpm: int = 80):
        """
        模拟打字：
        - 纯 ASCII 用 pyautogui.write() 逐字输入
        - 含中文用剪贴板粘贴（pyautogui.typewrite 不支持中文）
        """
        if not _PYAUTOGUI_OK:
            return
        if not text:
            return

        if _is_ascii(text):
            # 英文逐字输入，间隔模拟打字速度
            interval = 60.0 / (wpm * 5)  # WPM → 每字符秒数（≈5字符/词）
            pyautogui.write(text, interval=interval)
        else:
            # 含中文：用剪贴板粘贴
            if _CLIP_OK:
                original = pyperclip.paste()
                try:
                    pyperclip.copy(text)
                    _human_delay(0.1, 0.2)
                    pyautogui.hotkey("ctrl", "v")
                    time.sleep(0.25)
                finally:
                    if pyperclip.paste() == text:
                        pyperclip.copy(original)
            else:
                # 没有 pyperclip 的降级方案
                raise RuntimeError("中文输入需要 pyperclip")

    # ── 应用操作 ──────────────────────────────────────────
    def open_app(self, app_name: str):
        """Launch fixed Windows apps directly; use Start search for other names."""
        from core.action_router import APP_NAMES
        known = APP_NAMES.get(app_name.lower(), app_name.lower())
        if known in {"notepad", "calc", "mspaint"}:
            executable = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / (known + ".exe")
            if not executable.is_file():
                return "启动失败：找不到系统应用 " + known
            # Only these fixed system executables; never pass a model string to a shell.
            process = subprocess.Popen([str(executable)], shell=False)
            code = process.poll()
            if code not in (None, 0):
                return "启动失败：%s 返回 %s" % (known, code)
            return "已向 Windows 发送启动请求：%s（未核验窗口是否出现）" % known
        if not _PYAUTOGUI_OK:
            return f"pyautogui 未安装"

        print(f"[Desktop] Win 搜索打开：{app_name}")
        pyautogui.press("win")
        time.sleep(0.8)  # 等待开始菜单弹出
        self.type_text(app_name)
        time.sleep(0.5)  # 等待搜索结果出现
        pyautogui.press("enter")
        time.sleep(1.5)  # 等待应用启动
        return f"已提交开始菜单搜索并按回车：{app_name}（未核验应用是否启动）"

    def open_browser(self, url: str = ""):
        """
        打开/聚焦浏览器，可选直接导航到 URL。
        URL 交给系统默认浏览器；无 URL 时通过开始菜单打开 Edge。
        """
        if url:
            opened = webbrowser.open(url)
            return f"已将网址交给默认浏览器：{url}" if opened else f"浏览器未能打开网址：{url}"
        if not _PYAUTOGUI_OK:
            return "pyautogui 未安装"

        # 尝试用 Win 搜索打开 Edge（Windows 默认自带）
        print(f"[Desktop] 打开浏览器" + (f"，导航到 {url}" if url else ""))
        self.open_app("edge")
        time.sleep(1.0)

        return "已打开浏览器"

    def search_web(self, query: str, engine: str = "google", open_first: bool = False):
        """直接用 webbrowser.open 打开搜索 URL，最可靠。"""
        engine = engine.lower()
        url_template = SEARCH_ENGINES.get(engine, SEARCH_ENGINES["google"])
        url = url_template.format(quote_plus(query))

        print(f"[Desktop] 搜索「{query}」（{engine}）→ {url}")
        if not webbrowser.open(url):
            return "默认浏览器未能打开搜索页面"
        click_result = "未自动点击"
        if open_first is True:
            time.sleep(2.5)
            try:
                click_result = self.click_first_result()
            except Exception as e:
                click_result = "自动点击失败：" + type(e).__name__

        return f"已搜索：{query}（{engine}）。{click_result}"

    def click_first_result(self) -> str:
        """Shared visual service; reject missing, non-numeric and out-of-bounds coordinates."""
        if not _PYAUTOGUI_OK:
            return "pyautogui 未安装，未自动点击"
        if not getattr(self, "llm_client", None):
            return "未提供视觉服务，未自动点击"
        from core.screen import get_screen_capture
        from core.protocol import extract_object
        from core.coordinates import image_to_desktop
        try:
            capture = get_screen_capture()
            b64 = capture._capture_b64()
            monitor = dict(capture.monitor)
            from PIL import Image
            import base64
            import io
            with Image.open(io.BytesIO(base64.b64decode(b64))) as image:
                width, height = image.size
            prompt = (f"截图尺寸 {width}x{height}。找到第一条自然搜索结果的标题链接，忽略广告、登录和下载按钮。"
                      '只返回 JSON {"x": 数字, "y": 数字}；不确定返回 {"x": null, "y": null}。')
            raw = self.llm_client.vision_chat_local(prompt, b64)
            coords, _ = extract_object(raw)
            if not isinstance(coords, dict):
                return "未识别到有效搜索结果"
            x, y = coords.get("x"), coords.get("y")
            if isinstance(x, bool) or isinstance(y, bool) or not isinstance(x, (float, int)) or not isinstance(y, (float, int)):
                return "未找到可点击的搜索结果"
            try:
                real_x, real_y = image_to_desktop(x, y, width, height, monitor)
            except ValueError as exc:
                return str(exc) + "，取消点击"
            self.click(real_x, real_y)
            return "已点击第一条搜索结果"
        except Exception as exc:
            return "自动点击失败：" + type(exc).__name__


# ── 全局单例 ──────────────────────────────────────────────
_controller = HumanLikeController()


# ═══════════════════════════════════════════════════════════
#  execute_action — 入口函数（由 window.py _on_reply 调用）
# ═══════════════════════════════════════════════════════════
def execute_action(action: dict, llm_client=None) -> str:
    """
    执行 LLM 返回的 action。
    action 格式：{"type": "open/search/click/type/hotkey/scroll", ...}
    """
    if not isinstance(action, dict) or not isinstance(action.get("type"), str):
        return "[Desktop] 无效操作"
    action_type = action["type"].lower()
    if action_type == "blocked":
        return "[Desktop] 已取消操作：" + str(action.get("reason", "无效操作"))
    _controller.llm_client = llm_client
    if action_type not in {"open", "search"} and not _PYAUTOGUI_OK:
        return "[Desktop] pyautogui 未安装，未执行操作"

    try:
        if action_type == "open":
            return _do_open(action.get("target", ""))

        elif action_type == "search":
            return _do_search(
                action.get("query", ""),
                action.get("engine", "google"),
                action.get("open_first") is True,
            )

        elif action_type == "click":
            x, y = action.get("x"), action.get("y")
            if x is None or y is None:
                return "[Desktop] 缺少坐标"
            button = action.get("button", "left")
            if button not in {"left", "right", "middle"}:
                return "[Desktop] 不支持的鼠标按键"
            _controller.click(int(x), int(y), button)
            return f"已点击 ({x}, {y})"

        elif action_type == "type":
            text = action.get("text", "")
            if not text:
                return "[Desktop] 没有要输入的文字"
            if len(text) > 2000:
                return "[Desktop] 拒绝输入超过 2000 字符的内容"
            _controller.type_text(text)
            return f"已输入：{text}"

        elif action_type == "hotkey":
            keys = action.get("keys", [])
            if isinstance(keys, str):
                keys = [k.strip() for k in keys.split("+")]
            if not isinstance(keys, list) or not keys or any(not isinstance(k, str) for k in keys):
                return "[Desktop] 没有指定快捷键"
            if any(k.lower() not in pyautogui.KEYBOARD_KEYS for k in keys):
                return "[Desktop] 无效快捷键"
            _controller.hotkey(*keys)
            return f"已执行快捷键：{'+'.join(keys)}"

        elif action_type == "scroll":
            direction = action.get("direction", "down")
            if direction not in {"up", "down"}:
                return "[Desktop] 滚动方向无效"
            amount = max(1, min(int(action.get("amount", 3)), 20))
            _controller.scroll(direction, amount)
            return f"已滚动 {action.get('direction', 'down')}"

        else:
            return f"[Desktop] 未知操作类型：{action_type}"

    except Exception as e:
        print(f"[Desktop] 执行失败：{e}")
        return f"[Desktop] 执行失败：{e}"


def _do_open(target: str) -> str:
    """通过 Win 键搜索打开程序，或直接打开网址。"""
    if not target:
        return "[Desktop] 没有指定要打开的目标"
    if target in {"browser", "浏览器", "默认浏览器"}:
        return _controller.open_browser("about:blank")

    # 判断网址
    if target.startswith("http://") or target.startswith("https://"):
        return _controller.open_browser(target)
    if "." in target and " " not in target and "/" in target:
        return _controller.open_browser("https://" + target)

    # 程序名：用 Win 键搜索
    return _controller.open_app(target)


def _do_search(query: str, engine: str = "google", open_first: bool = False) -> str:
    """搜索引擎搜索。"""
    if not query:
        return "[Desktop] 没有搜索内容"
    return _controller.search_web(query, engine, open_first)
