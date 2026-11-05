# ui/window.py — 明日方舟风格（边流式边解析 + 逐句演出版）

import sys
import json
from typing import Optional, List, Tuple
from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout, QSizePolicy, QMessageBox,
)
from PyQt6.QtCore import Qt, QTimer, QPoint, pyqtSignal, pyqtSlot

from ui.avatar import AvatarManager


from ui.workers import LLMWorker, ActionWorker
from ui.workers import ClientLoader
from ui.playback import SentencePlayer
from ui.preferences import WindowPreferences
from ui.window_controls import WindowControls
from ui.pet_toolbar import PetToolbar
from core.companion_commands import companion_command
from core.action_router import direct_request, validate_action
from core.context import capture_intent
from core.social import SessionState, get_session_state, build_greeting, departure_intent, farewell_sentences
from config import (ASR_ENABLED, PROACTIVE_ENABLED, BUBBLE_MIN_WIDTH, BUBBLE_MIN_HEIGHT,
                    BUBBLE_MAX_WIDTH, BUBBLE_MAX_HEIGHT)
import time


from ui.widgets import AKBubble, AKInputBar


# ── 主窗口 ────────────────────────────────────────────────
class CompanionWindow(QWidget):

    asr_text_received = pyqtSignal(str)
    screen_change_received = pyqtSignal(list)
    closed = pyqtSignal()

    WIN_W = 560
    WIN_H = 960

    def __init__(self, llm_client=None, initialize_client=False, use_memory=True, initialize_sensors=True, preferences=None):
        super().__init__()
        self.llm_client = llm_client
        self._use_memory = use_memory
        self._initialize_sensors = initialize_sensors
        self._worker: Optional[LLMWorker] = None
        self._drag_pos = QPoint()
        self._busy = False

        self._screen_capture = None
        self._camera_capture = None
        self._screen_watcher = None
        self._pending_proactive: List[Tuple[float, List[dict]]] = []
        self._action_workers: List[ActionWorker] = []
        self._shutdown_done = False
        self._closing = False
        self._last_user_activity = time.monotonic()
        self._action_queue = []
        self._last_requested_action = None
        self._last_requested_at = 0.0
        self._action_user_input = ""
        self._action_turn_recorded = False
        self._confirming_action = False
        self._pending_asr = ""
        self._asr_draft = ""
        self._last_visual_at = 0.0
        self._last_visual_channel = "screen"
        self._threads = []
        self._draft_present = False
        self._preview_text = ""
        self._received_sentence = False
        self._greeting_active = False
        self._greeting_started = False
        self._has_user_turn = False
        self._opening = None
        self._farewell_active = False
        self._preferences = preferences if preferences is not None else WindowPreferences()
        self._quiet_mode = self._preferences.quiet
        self._last_pet_at = 0.0
        self._pet_count = 0

        self._build_window()
        self._build_ui()

        self._sentence_player = SentencePlayer(self)
        self._farewell_timer = QTimer(self)
        self._farewell_timer.setSingleShot(True)
        self._farewell_timer.timeout.connect(self.close)
        self._prefetch_timer = QTimer(self)
        self._prefetch_timer.setSingleShot(True)
        self._prefetch_timer.timeout.connect(self._prefetch_memory)
        self.input_bar.input_box.textEdited.connect(self._draft_edited)
        self.input_bar.input_box.textChanged.connect(self._draft_changed)
        self.asr_text_received.connect(
            self._handle_asr_text, Qt.ConnectionType.QueuedConnection
        )
        self.screen_change_received.connect(
            self._handle_screen_change, Qt.ConnectionType.QueuedConnection
        )
        self._pet_toolbar = PetToolbar(self)
        self._controls = WindowControls(self, self._preferences)

        if initialize_sensors:
            self._init_screen_capture()
            self._init_camera()
            if ASR_ENABLED:
                self._init_asr()

        if PROACTIVE_ENABLED and initialize_sensors:
            QTimer.singleShot(2000, self._init_screen_watcher)
        if initialize_client and self.llm_client is None:
            self.input_bar.btn.setEnabled(False)
            self.status_label.setText("连接模块初始化中…")
            self.status_label.show()
            QTimer.singleShot(200, self._init_client)

    def _init_client(self):
        if self._closing:
            return
        loader = ClientLoader(use_memory=self._use_memory)
        self._threads.append(loader)
        loader.client_ready.connect(self._on_client_ready, Qt.ConnectionType.QueuedConnection)
        loader.failed.connect(self._on_client_error, Qt.ConnectionType.QueuedConnection)
        loader.finished.connect(self._thread_finished, Qt.ConnectionType.QueuedConnection)
        loader.start()

    @pyqtSlot(object)
    def _on_client_ready(self, client):
        if self._closing:
            client.close()
            return
        self.llm_client = client
        self._share_opening()
        self.input_bar.btn.setEnabled(True)
        self.status_label.hide()
        import logging
        logging.info("Conversation client ready; optional model/memory warmup continues in background")
        if PROACTIVE_ENABLED and self._initialize_sensors and not self._farewell_active:
            self._init_screen_watcher()
        if self._asr_draft and (not self._busy or self._greeting_active or departure_intent(self._asr_draft)):
            QTimer.singleShot(500, lambda: self._auto_send_asr(self._asr_draft))

    @pyqtSlot(str)
    def _on_client_error(self, message):
        self.status_label.setText(message)
        self.status_label.show()

    def _init_screen_capture(self):
        import threading
        def _start():
            try:
                from core.screen import get_screen_capture
                self._screen_capture = get_screen_capture()
                if not self._shutdown_done:
                    self._screen_capture.start()
            except Exception as e:
                print(f"[Window] 屏幕感知启动失败：{e}")
        threading.Thread(target=_start, daemon=True).start()

    def _init_camera(self):
        import threading
        def _start():
            try:
                from core.camera import get_camera_capture
                self._camera_capture = get_camera_capture()
                print("[Window] 摄像头模块已加载，设备将在明确请求时按需打开")
            except Exception as e:
                print(f"[Window] 摄像头启动失败（将无摄像头视觉）：{e}")
        threading.Thread(target=_start, daemon=True).start()

    def _init_asr(self):
        import threading
        def _start():
            try:
                from core.asr import get_asr_listener
                self._asr = get_asr_listener(on_text=self.asr_text_received.emit)
                if not self._shutdown_done:
                    self._asr.start()
            except Exception as e:
                print(f"[Window] ASR启动失败：{e}")
        threading.Thread(target=_start, daemon=True).start()

    def _init_screen_watcher(self):
        if self._shutdown_done or self._farewell_active or self._quiet_mode or not self.llm_client:
            return
        import threading
        exclude_rect = self._physical_rect()
        def _start():
            try:
                from core.screen_watcher import get_screen_watcher
                self._screen_watcher = get_screen_watcher(
                    on_change=self.screen_change_received.emit,
                    llm_client=self.llm_client,
                    screen_capture=self._screen_capture,
                )
                self._screen_watcher.can_observe = self._can_observe
                self._screen_watcher.exclude_rect = exclude_rect
                if not self._shutdown_done:
                    self._screen_watcher.start()
            except Exception as e:
                print(f"[Window] 主动屏幕感知启动失败：{e}")
        threading.Thread(target=_start, daemon=True).start()

    def _build_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        screen = QApplication.primaryScreen().availableGeometry()
        self.WIN_H = min(self.WIN_H, screen.height() - 30)
        self.WIN_W = min(self.WIN_W, max(340, int(self.WIN_H * 0.60)), screen.width())
        self.setFixedSize(self.WIN_W, self.WIN_H)
        self.move(
            max(screen.left(), screen.right() - self.WIN_W - 20),
            max(screen.top(),  screen.bottom() - self.WIN_H - 20),
        )

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.avatar_label = QLabel()
        self.avatar_label.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom
        )
        self.avatar_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        root.addWidget(self.avatar_label, alignment=Qt.AlignmentFlag.AlignHCenter)

        bottom = QVBoxLayout()
        self._bottom_layout = bottom
        bottom.setContentsMargins(12, 0, 12, 12)
        bottom.setSpacing(6)
        bottom.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.bubble = AKBubble()
        self.bubble.set_width_limit(self.WIN_W - 24)
        avatar_width = self.WIN_W - 64
        self.bubble.set_minimum_extent(max(BUBBLE_MIN_WIDTH, avatar_width + 20), BUBBLE_MIN_HEIGHT)
        self.bubble.set_maximum_extent(
            min(self.WIN_W - 24, max(avatar_width + 20, BUBBLE_MAX_WIDTH)), BUBBLE_MAX_HEIGHT)
        self.bubble.hide()
        bottom.addWidget(self.bubble, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.input_bar = AKInputBar()
        self.input_bar.send_signal.connect(self._send)
        self.input_bar.cancel_signal.connect(self._cancel_reply)
        bottom.addWidget(self.input_bar)
        self.status_label = QLabel()
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        self.status_label.setWordWrap(True)
        self.status_label.setMaximumHeight(60)
        self.status_label.setStyleSheet("color: #ddd; background: rgba(10,12,18,180); padding: 3px;")
        self.status_label.hide()
        bottom.addWidget(self.status_label)

        root.addLayout(bottom)
        root.addStretch(1)

        self.avatar_mgr = AvatarManager(
            self.avatar_label,
            size=(avatar_width, max(180, self.WIN_H - 235)),
            crop_ratio=0.55,
        )
        pixmap = self.avatar_label.pixmap()
        if pixmap and not pixmap.isNull():
            avatar_height = min(self.avatar_label.height(), pixmap.height() + 8)
            self.avatar_mgr.set_size((avatar_width, avatar_height))
            self.WIN_H = min(self.WIN_H, avatar_height + 312)
            self.setFixedSize(self.WIN_W, self.WIN_H)
            screen = QApplication.primaryScreen().availableGeometry()
            self.move(max(screen.left(), screen.right() - self.WIN_W - 20),
                      max(screen.top(), screen.bottom() - self.WIN_H - 20))

        # Leave room for input, action feedback and margins even on a short screen.
        available = self.WIN_H - self.avatar_label.height() - 124
        self.bubble.set_height_limit(min(BUBBLE_MAX_HEIGHT, available))

    def _show_bubble(self, text: str, full_text=None):
        self.bubble.setText(text, sizing_text=full_text)
        self.bubble.show()
        self.bubble.update()

    def _lock(self):
        self._busy = True
        self.input_bar.set_enabled(False)

    def _unlock(self):
        self._greeting_active = False
        if self._farewell_active:
            if not self._farewell_timer.isActive():
                self._farewell_timer.start(1500)
            return
        if self._action_workers or self._action_queue or self._confirming_action:
            return
        self._busy = False
        self.input_bar.set_enabled(True)
        self.input_bar.btn.setEnabled(self.llm_client is not None)
        if self._pending_proactive and self._can_observe():
            timestamp, sentences = self._pending_proactive.pop()
            self._pending_proactive.clear()
            if time.monotonic() - timestamp > 12:
                return
            self._lock()
            self._play_proactive(sentences)

    def _draft_edited(self, text):
        if self._farewell_active:
            self._cancel_reply()
        self._last_user_activity = time.monotonic()
        self._asr_draft = ""
        gateway = getattr(self.llm_client, "vision", None)
        if gateway:
            if text.strip():
                gateway.foreground_requested.set()
            elif not self._busy:
                gateway.foreground_requested.clear()

    def _draft_changed(self, text):
        self._draft_present = bool(text.strip())
        if self._draft_present:
            self._prefetch_timer.start(200)
        else:
            self._prefetch_timer.stop()

    def _prefetch_memory(self):
        prefetch = getattr(self.llm_client, "prefetch_memory", None)
        if prefetch and not self._closing:
            prefetch(self.input_bar.text().strip())

    def _can_observe(self):
        return (not self._quiet_mode and not self._busy and not self._closing and not self._draft_present
                and time.monotonic() - self._last_user_activity > 8)

    # ── ASR 回调 ──────────────────────────────────────────
    @pyqtSlot(str)
    def _handle_asr_text(self, text: str):
        if self._closing or not text.strip():
            return
        if self._farewell_active:
            if departure_intent(text):
                return
            self._cancel_reply()
        self._last_user_activity = time.monotonic()
        gateway = getattr(self.llm_client, "vision", None)
        if gateway:
            gateway.foreground_requested.set()
        if self.input_bar.text().strip():
            self._pending_asr = text
            self.status_label.setText("语音待确认：" + text[:80])
            self.status_label.show()
            return
        self.input_bar.input_box.setText(text)
        self._asr_draft = text
        if not self._busy or self._greeting_active or departure_intent(text) or companion_command(text):
            QTimer.singleShot(500, lambda: self._auto_send_asr(text))

    def _auto_send_asr(self, original_text: str):
        current = self.input_bar.input_box.text().strip()
        ready = not self._busy or self._greeting_active or departure_intent(original_text) or companion_command(original_text)
        if current == original_text.strip() and self._asr_draft == original_text and ready:
            self._send(current, source="asr")

    # ── 主动屏幕感知回调 ─────────────────────────────────
    @pyqtSlot(list)
    def _handle_screen_change(self, sentences: list):
        if self._closing or self._quiet_mode or self._farewell_active or self.input_bar.text().strip():
            return
        if self._busy or self._sentence_player.is_playing():
            self._pending_proactive[:] = [(time.monotonic(), sentences)]
        else:
            self._lock()
            self._play_proactive(sentences)

    def _play_proactive(self, sentences):
        record = getattr(self.llm_client, "record_utterance", None)
        if record:
            record("\n".join(sentence["text"] for sentence in sentences))
        self._sentence_player.play(sentences)

    # ── 发送消息 ──────────────────────────────────────────
    def _send(self, text: str, source: str = "text"):
        if self._closing:
            return
        if departure_intent(text):
            self._start_farewell()
            return
        if self._farewell_active:
            self._cancel_reply()
        command = companion_command(text)
        if command:
            self._run_companion_command(command)
            self.input_bar.clear()
            self._asr_draft = ""
            self._has_user_turn = True
            return
        previous = self._last_requested_action if time.monotonic() - self._last_requested_at < 120 else None
        direct = direct_request(text, previous)
        if not self.llm_client and direct is None:
            return
        if self._greeting_active:
            self._sentence_player.stop()
            self._greeting_active = False
            self._busy = False
        if self._busy:
            return
        if self._worker is not None and self._worker.isRunning():
            return

        if self._asr_draft == text:
            source = "asr"
        self._has_user_turn = True
        self._action_user_input = text
        self._action_turn_recorded = False

        self.input_bar.clear()
        self._last_user_activity = time.monotonic()
        self._asr_draft = ""
        self._pending_asr = ""
        self._pending_proactive.clear()
        self.status_label.hide()
        self._sentence_player.begin()
        self._received_sentence = False
        self._preview_text = ""
        self._lock()
        self._show_bubble("……")

        if direct is not None:
            import logging
            if direct.action:
                self._last_requested_action = dict(direct.action)
                self._last_requested_at = time.monotonic()
                logging.info("[Action] direct_request type=%s", direct.action["type"])
                self._show_bubble("正在打开搜索结果页。" if direct.action["type"] == "search" else "已收到打开请求，等你确认后执行。")
                self._execute_action_async(direct.action)
            else:
                self._show_bubble(direct.clarification)
                self._on_action_result("未执行：操作目标不明确。")
            self._unlock()
            return

        self._last_requested_action = None

        recent = self._last_visual_channel if time.monotonic() - self._last_visual_at < 45 else False
        need_screen, need_camera = capture_intent(text, recent)
        if need_screen or need_camera:
            self._last_visual_at = time.monotonic()
            self._last_visual_channel = "both" if need_screen and need_camera else "screen" if need_screen else "camera"

        self._worker = LLMWorker(
            self.llm_client, text,
            screen_capture=self._screen_capture,
            need_screen=need_screen,
            camera_capture=self._camera_capture,
            need_camera=need_camera,
            source=source,
        )
        self._worker.sentence_ready.connect(
            self._on_sentence_ready, Qt.ConnectionType.QueuedConnection
        )
        self._worker.preview_ready.connect(self._on_preview, Qt.ConnectionType.QueuedConnection)
        self._worker.stream_finished.connect(
            self._on_stream_finished, Qt.ConnectionType.QueuedConnection
        )
        self._worker.failed.connect(
            self._on_error, Qt.ConnectionType.QueuedConnection
        )
        self._worker.action_ready.connect(self._on_action_ready, Qt.ConnectionType.QueuedConnection)
        self._worker.action_missing.connect(self._on_plan_missing, Qt.ConnectionType.QueuedConnection)
        self._threads.append(self._worker)
        self._worker.finished.connect(self._thread_finished, Qt.ConnectionType.QueuedConnection)
        self._worker.start()

    @pyqtSlot()
    def _thread_finished(self):
        worker = self.sender()
        if worker in self._threads:
            self._threads.remove(worker)
        if worker.cancelled.is_set() and not self._closing and not self._farewell_active:
            self._unlock()
        if self._closing and not self._threads and not self._action_workers:
            self.close()

    @pyqtSlot(str, str, str)
    def _on_sentence_ready(self, text: str, emotion: str, action_json: str):
        """每个句子到达即入队播放。"""
        if self._closing or (self._worker and self._worker.cancelled.is_set()):
            return
        if self._worker:
            self._worker.metrics.mark("ui_sentence_received")
        self._received_sentence = True
        self._sentence_player.enqueue(text, emotion, action_json)

    @pyqtSlot(str)
    def _on_preview(self, text):
        if self._closing or self._received_sentence or (self._worker and self._worker.cancelled.is_set()):
            return
        self._preview_text, _ = self.bubble.take_page(text)
        if self._worker:
            self._worker.metrics.mark("ui_first_visible")
        self._show_bubble(self._preview_text)

    @pyqtSlot()
    def _on_stream_finished(self):
        """流结束，通知播放器播完队列后解锁。"""
        if self._closing or self._farewell_active or (self._worker and self._worker.cancelled.is_set()):
            return
        self._sentence_player.mark_stream_done()

    def _cancel_reply(self):
        self._farewell_active = False
        self._farewell_timer.stop()
        self._greeting_active = False
        self._sentence_player.stop()
        self._prefetch_timer.stop()
        self._action_queue.clear()
        for worker in self._action_workers:
            worker.cancelled.set()
        if self._worker and self._worker.isRunning():
            self._worker.cancelled.set()
            self.status_label.setText("正在停止生成…")
            self.status_label.show()
        else:
            self._unlock()

    @pyqtSlot(str)
    def _on_error(self, msg: str):
        if self._closing or self._farewell_active:
            return
        self._sentence_player.stop()
        self._action_queue.clear()
        self._pending_proactive.clear()
        self.avatar_mgr.set_emotion("sad")
        self._show_bubble(f"［ERROR］{msg}")
        self._unlock()

    def _execute_action_async(self, action: dict):
        if self._closing:
            return
        import logging
        try:
            action = validate_action(action)
        except ValueError as exc:
            self._on_action_result("未执行：" + str(exc))
            return
        if self._confirming_action:
            self._on_action_result("未执行：前一个操作仍在等待确认。")
            return
        action_type = str(action.get("type", "")).lower()
        needs_confirmation = action_type in {"open", "click", "type", "hotkey", "scroll"}
        needs_confirmation |= action_type == "search" and action.get("open_first") is True
        if needs_confirmation:
            logging.info("[Action] awaiting_confirmation type=%s", action_type)
            self.status_label.setText("等待确认：" + action_type)
            self.status_label.show()
            focus_note = ("\n\n确认后有 3 秒，请切换到目标应用并选中输入位置；"
                          "若焦点仍在小乐窗口则取消。执行期间请勿切换窗口。"
                          if action_type in {"type", "hotkey"} else "")
            self._confirming_action = True
            try:
                answer = QMessageBox.question(
                    self, "确认桌面操作",
                    f"小乐请求执行：{action_type}\n\n{json.dumps(action, ensure_ascii=False)}{focus_note}",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No)
            finally:
                self._confirming_action = False
            if answer != QMessageBox.StandardButton.Yes or self._closing:
                self._on_action_result("未执行：用户取消了操作。")
                return

        logging.info("[Action] queued type=%s", action_type)
        self.status_label.setText("正在执行：" + action_type)
        self.status_label.show()
        self._action_queue.append(action)
        self._start_next_action()

    @pyqtSlot(str)
    def _on_action_ready(self, action_json):
        if self._closing or self._farewell_active or (self._worker and self._worker.cancelled.is_set()):
            return
        try:
            action = json.loads(action_json)
        except ValueError:
            self._on_action_result("未执行：操作指令无法解析。")
            return
        self._execute_action_async(action)
        if not self._sentence_player.is_playing() and not (self._worker and self._worker.isRunning()):
            self._unlock()

    @pyqtSlot(str)
    def _on_plan_missing(self, message):
        if self._closing or (self._worker and self._worker.cancelled.is_set()):
            return
        self._on_action_result(message)

    def _start_next_action(self):
        if self._action_workers or not self._action_queue or self._closing:
            return
        worker = ActionWorker(self._action_queue.pop(0), self.llm_client)
        self._action_workers.append(worker)
        if str(worker.action.get("type", "")).lower() in {"type", "hotkey"}:
            self.status_label.setText("3 秒后执行键盘操作，请切换到目标应用；点停止可取消等待。")
            self.status_label.show()

        def cleanup():
            if worker in self._action_workers:
                self._action_workers.remove(worker)
            worker.deleteLater()
            self._start_next_action()
            if self._closing and not self._threads and not self._action_workers:
                self.close()
            elif not self._sentence_player.is_playing() and not (self._worker and self._worker.isRunning()):
                self._unlock()

        worker.completed.connect(
            self._on_action_result,
            Qt.ConnectionType.QueuedConnection,
        )
        worker.failed.connect(
            self._on_action_result,
            Qt.ConnectionType.QueuedConnection,
        )
        worker.finished.connect(cleanup, Qt.ConnectionType.QueuedConnection)
        worker.start()

    @pyqtSlot(str)
    def _on_action_result(self, result):
        import logging
        logging.info("[Action] executor_feedback_received")
        print("[Desktop] " + result)
        if self.llm_client:
            self.llm_client.record_action(result)
            record = getattr(self.llm_client, "record_tool_turn", None)
            if record and self._action_user_input and not self._action_turn_recorded:
                record(self._action_user_input, result)
                self._action_turn_recorded = True
        if not self._closing and not self._farewell_active:
            self.status_label.setText(result[:160])
            self.status_label.show()

    def say(self, text: str, emotion: str = "neutral"):
        self.avatar_mgr.set_emotion(emotion)
        self._show_bubble(text)

    def _set_quiet(self, quiet):
        self._quiet_mode = quiet
        if hasattr(self, "_pet_toolbar"):
            self._pet_toolbar.sync_quiet()
        self._pending_proactive.clear()
        self._controls.changed()
        if not quiet and PROACTIVE_ENABLED and self._initialize_sensors:
            self._init_screen_watcher()

    def _local_reply(self, text, emotion="neutral"):
        self._last_user_activity = time.monotonic()
        if self._busy and not self._greeting_active:
            self.status_label.setText(text)
            self.status_label.show()
            return
        self._greeting_active = False
        self._lock()
        self._sentence_player.play([{"text": text, "emotion": emotion}])
        record = getattr(self.llm_client, "record_utterance", None)
        if record:
            record(text)

    def _run_companion_command(self, command):
        if command in {"smaller", "larger", "reset_size"}:
            target = 1.0 if command == "reset_size" else self._controls._target_scale * (1.1 if command == "larger" else 1 / 1.1)
            self._controls.request_scale(target)
            reply = "调到 %d%% 大小，我就在这儿。" % round(self._controls._target_scale * 100)
        elif command in {"quiet", "talk"}:
            self._set_quiet(command == "quiet")
            reply = "好，我安静待着。你找我时再聊。" if self._quiet_mode else "好，恢复主动聊天。能观察时，我再接话。"
        else:
            self._controls.dock(command)
            reply = "挪到%s边啦，不挡你。" % ("左" if command == "left" else "右")
        record = getattr(self.llm_client, "record_action", None)
        if record:
            record("小乐自身状态：" + reply)
        self._local_reply(reply)

    def _pet_interact(self):
        now = time.monotonic()
        if self._busy or self._farewell_active or self.input_bar.text().strip() or now - self._last_pet_at < 8:
            return
        self._last_pet_at = now
        responses = ("在呢，老板。", "嗯？我在这边。", "收到，注意到你啦。")
        self._local_reply(responses[self._pet_count % len(responses)], "happy")
        self._pet_count += 1

    def start_greeting(self, state=None, now=None):
        if self._greeting_started or self._closing or self._busy or self._has_user_turn or self.input_bar.text().strip():
            return
        self._greeting_started = True
        state = state if state is not None else (get_session_state() if self._use_memory else SessionState())
        self._opening = build_greeting(state, now)
        self._share_opening()
        self._greeting_active = True
        self._lock()
        self._sentence_player.play(self._opening.sentences)
        self.input_bar.btn.setEnabled(self.llm_client is not None)

    def _share_opening(self):
        if self._opening and self.llm_client and hasattr(self.llm_client, "set_opening"):
            self.llm_client.set_opening("\n".join(s["text"] for s in self._opening.sentences),
                                        self._opening.previous_context)

    def _start_farewell(self):
        if self._farewell_active:
            return
        self._farewell_active = True
        self._greeting_active = False
        self._preview_text = ""
        self._pending_proactive.clear()
        self._action_queue.clear()
        for worker in self._action_workers:
            worker.cancelled.set()
        self._prefetch_timer.stop()
        self._pending_asr = self._asr_draft = ""
        self.input_bar.clear()
        self.status_label.hide()
        if self._worker and self._worker.isRunning():
            self._worker.cancelled.set()
        self._lock()
        self._sentence_player.play(farewell_sentences())
        # A new message or the stop button can cancel the pending exit.
        self.input_bar.btn.setEnabled(True)

    # ── 拖动窗口 ──────────────────────────────────────────
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and not self._drag_pos.isNull():
            self._last_user_activity = time.monotonic()
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event):
        self._drag_pos = QPoint()
        if not self._controls._apply_timer.isActive():
            self._controls.set_scale(self._controls.scale, event.globalPosition().toPoint())
        self._controls.changed()
        self._sync_observation_rect()

    def _sync_observation_rect(self):
        if self._screen_watcher:
            self._screen_watcher.exclude_rect = self._physical_rect()

    def _physical_rect(self):
        try:
            import ctypes
            from ctypes import wintypes
            rect = wintypes.RECT()
            get_rect = ctypes.windll.user32.GetWindowRect
            get_rect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
            if get_rect(int(self.winId()), ctypes.byref(rect)):
                return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
        except (AttributeError, OSError):
            pass
        return self.x(), self.y(), self.width(), self.height()

    def contextMenuEvent(self, event):
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: rgba(10, 12, 18, 230);
                color: #e8e4d8;
                border: 1px solid rgba(180, 160, 100, 120);
                padding: 4px;
                font-size: 12px;
            }
            QMenu::item:selected { background: rgba(180, 160, 100, 40); }
        """)
        adopt = menu.addAction("采用待确认语音") if self._pending_asr else None
        copy_reply = menu.addAction("复制完整回复")
        menu.addSeparator()
        size_menu = menu.addMenu("大小 (%d%%)" % round(self._controls.scale * 100))
        size_menu.addAction("放大").triggered.connect(lambda: self._controls.zoom_by(1.1))
        size_menu.addAction("缩小").triggered.connect(lambda: self._controls.zoom_by(1 / 1.1))
        size_menu.addAction("恢复默认大小").triggered.connect(lambda: self._controls.request_scale(1.0))
        quiet_action = menu.addAction("安静陪伴")
        quiet_action.setCheckable(True)
        quiet_action.setChecked(self._quiet_mode)
        quiet_action.toggled.connect(self._set_quiet)
        position_menu = menu.addMenu("位置")
        position_menu.addAction("左下角").triggered.connect(lambda: self._controls.dock("left"))
        position_menu.addAction("右下角").triggered.connect(lambda: self._controls.dock("right"))
        menu.addSeparator()
        exit_action = menu.addAction("退出")
        selected = menu.exec(event.globalPos())
        if adopt and selected == adopt:
            self.input_bar.input_box.setText(self.input_bar.text() + self._pending_asr)
            self._pending_asr = ""
            self.status_label.hide()
        elif selected == copy_reply:
            if self.llm_client and self.llm_client.last_reply:
                QApplication.clipboard().setText(self.llm_client.last_reply)
        elif selected == exit_action:
            self.close()

    def shutdown(self):
        if self._shutdown_done:
            return
        self._shutdown_done = True
        self._pet_toolbar.shutdown()
        self._controls.close()
        self._farewell_timer.stop()
        self._sentence_player.stop()
        self._action_queue.clear()
        for worker in self._threads:
            worker.cancelled.set()
        for worker in self._action_workers:
            worker.cancelled.set()
        for obj_name in ("_asr", "_camera_capture", "_screen_capture", "_screen_watcher"):
            obj = getattr(self, obj_name, None)
            if obj and hasattr(obj, "stop"):
                try:
                    obj.stop()
                except Exception as exc:
                    print(f"[Window] 停止 {obj_name} 失败：{exc}")
        if not self._threads and not self._action_workers and self.llm_client and hasattr(self.llm_client, "close"):
            self.llm_client.close()

    def closeEvent(self, event):
        self._closing = True
        self.shutdown()
        if self._threads or self._action_workers:
            self.hide()
            event.ignore()
            return
        if self.llm_client and hasattr(self.llm_client, "close"):
            self.llm_client.close()
        event.accept()
        self.closed.emit()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = CompanionWindow(llm_client=None)
    win.closed.connect(app.quit)
    win.show()
    QTimer.singleShot(400, win.start_greeting)
    sys.exit(app.exec())
