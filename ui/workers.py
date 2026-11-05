"""Blocking I/O workers. Widgets are only touched by queued signals in window.py."""
import json
import logging
import threading
from PyQt6.QtCore import QThread, pyqtSignal
from core.metrics import TurnMetrics
from core.context import action_intent
from core.action_router import validate_action


class ClientLoader(QThread):
    client_ready = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, use_memory=True, factory=None):
        super().__init__()
        self.use_memory, self.factory = use_memory, factory
        self.cancelled = threading.Event()

    def run(self):
        try:
            factory = self.factory
            if factory is None:
                from core.llm import LLMClient
                factory = LLMClient
            client = factory(use_memory=self.use_memory)
            if self.cancelled.is_set():
                client.close()
            else:
                self.client_ready.emit(client)
        except Exception as exc:
            if not self.cancelled.is_set():
                self.failed.emit("连接模块初始化失败：" + type(exc).__name__)


class LLMWorker(QThread):
    sentence_ready = pyqtSignal(str, str, str)
    preview_ready = pyqtSignal(str)
    stream_finished = pyqtSignal()
    failed = pyqtSignal(str)
    action_ready = pyqtSignal(str)
    action_missing = pyqtSignal(str)

    def __init__(self, llm_client, text, screen_capture=None, need_screen=False,
                 camera_capture=None, need_camera=False, source="text"):
        super().__init__()
        self.llm_client, self.text, self.source = llm_client, text, source
        self._screen_capture, self._need_screen = screen_capture, need_screen
        self._camera_capture, self._need_camera = camera_capture, need_camera
        self.cancelled = threading.Event()
        self.metrics = TurnMetrics(source)

    def run(self):
        try:
            operation_turn = action_intent(self.text)
            planned_action = None
            plan_error = ""
            images, notes = {}, []
            for name, needed, capture in (("screen", self._need_screen, self._screen_capture),
                                          ("camera", self._need_camera, self._camera_capture)):
                if not needed:
                    images[name] = ""
                    continue
                try:
                    images[name] = capture.capture_b64() if capture else ""
                except Exception as exc:
                    logging.warning("%s capture failed: %s", name, type(exc).__name__)
                    images[name] = ""
                if not images[name]:
                    notes.append(name + "画面获取失败；不能猜测这路画面的内容。")
            self.metrics.mark("capture_ready")
            image_size = None
            monitor = None
            if images["screen"]:
                import base64
                import io
                from PIL import Image
                with Image.open(io.BytesIO(base64.b64decode(images["screen"]))) as image:
                    image_size = image.size
                monitor = dict(self._screen_capture.monitor)
                notes.append("屏幕截图尺寸 %sx%s；click 坐标使用截图像素，客户端会换算成真实桌面坐标。" % image_size)
            if self.cancelled.is_set():
                return
            for sentence in self.llm_client.chat_stream(
                self.text, screen_b64=images["screen"], camera_b64=images["camera"],
                source=self.source, notes="\n".join(notes), stop_event=self.cancelled, metrics=self.metrics,
                preview_callback=None if operation_turn else self.preview_ready.emit,
                record_turn=not operation_turn,
            ):
                if self.cancelled.is_set():
                    return
                action = sentence.get("action")
                if action and str(action.get("type", "")).lower() == "search":
                    from core.companion_commands import first_result_requested
                    action = dict(action, open_first=(action.get("open_first") is True
                                                     and first_result_requested(self.text)))
                if action and str(action.get("type", "")).lower() == "click":
                    if image_size:
                        from core.coordinates import image_to_desktop
                        try:
                            x, y = image_to_desktop(action.get("x"), action.get("y"), *image_size, monitor)
                            action = dict(action, x=x, y=y)
                        except ValueError as exc:
                            action = {"type": "blocked", "reason": str(exc)}
                    elif self._need_screen or self._need_camera:
                        action = {"type": "blocked", "reason": "没有有效屏幕画面，不能根据猜测或摄像头画面点击桌面"}
                if operation_turn:
                    if action and planned_action is None:
                        try:
                            planned_action = validate_action(action)
                        except ValueError as exc:
                            plan_error = str(exc)
                    continue
                self.sentence_ready.emit(sentence["text"], sentence["emotion"], "")
            if not self.cancelled.is_set():
                if operation_turn:
                    if planned_action is not None:
                        logging.info("[Action] plan_ready type=%s", planned_action["type"])
                        self.sentence_ready.emit("操作指令已就绪。", "neutral", "")
                        self.action_ready.emit(json.dumps(planned_action, ensure_ascii=False))
                    else:
                        message = "未执行：" + (plan_error or "模型只返回了文字，没有生成有效操作指令。请明确应用名或操作目标。")
                        logging.warning("[Action] no_valid_plan")
                        self.sentence_ready.emit(message, "thinking", "")
                        self.action_missing.emit(message)
                self.stream_finished.emit()
        except Exception as exc:
            logging.error("Reply failed: %s", type(exc).__name__)
            if not self.cancelled.is_set():
                self.failed.emit("连接或生成失败，请重试（" + type(exc).__name__ + "）")


class ActionWorker(QThread):
    completed = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, action, llm_client=None):
        super().__init__()
        self.action, self.llm_client = action, llm_client
        self.cancelled = threading.Event()

    def run(self):
        try:
            if self.cancelled.is_set():
                return
            if str(self.action.get("type", "")).lower() in {"type", "hotkey"}:
                if self.cancelled.wait(3.0):
                    return
                from core.desktop_focus import external_window_focused
                if not external_window_focused():
                    self.completed.emit("未切换到其他应用窗口，已取消键盘操作")
                    return
            from core.desktop import execute_action
            if not self.cancelled.is_set():
                logging.info("[Action] executor_started type=%s", self.action.get("type"))
                self.completed.emit(execute_action(self.action, self.llm_client))
        except Exception as exc:
            self.failed.emit("操作失败：" + type(exc).__name__)
