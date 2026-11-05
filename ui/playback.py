"""Stream speech into bounded pages; presentation and timers stay on Qt's thread."""
import json
import time
from collections import deque
from PyQt6.QtCore import QObject, QTimer


class SentencePlayer(QObject):
    CHAR_INTERVAL = 18

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self._queue = deque()
        self._type_timer = QTimer(self)
        self._type_timer.timeout.connect(self._type_next_char)
        self._pause_timer = QTimer(self)
        self._pause_timer.setSingleShot(True)
        self._pause_timer.timeout.connect(self._play_next)
        self.stop()

    def begin(self):
        self.stop()

    def stop(self):
        self._type_timer.stop()
        self._pause_timer.stop()
        self._queue.clear()
        self._playing = False
        self._stream_done = False
        self._current_text = ""
        self._page_text = ""
        self._page_prefix = ""
        self._page_finished_at = 0.0
        self._awaiting_page = False
        self._index = 0
        self._action = None

    def enqueue(self, text, emotion, action_json=""):
        if not text:
            return
        try:
            action = json.loads(action_json) if action_json else None
        except (ValueError, TypeError):
            action = None
        self._queue.append({"text": text, "emotion": emotion, "action": action})
        if not self._playing:
            self._play_next()

    def play(self, sentences):
        self.begin()
        for sentence in sentences:
            action = sentence.get("action")
            self.enqueue(sentence["text"], sentence.get("emotion", "neutral"),
                         json.dumps(action) if action else "")
        self.mark_stream_done()

    def mark_stream_done(self):
        self._stream_done = True
        if not self._queue and not self._type_timer.isActive():
            self._play_next()

    def is_playing(self):
        return self._playing or bool(self._queue)

    def reflow(self):
        """Keep all content/actions when font rounding changes a page's capacity."""
        if not self._page_text:
            return
        visible = self._page_prefix + self._current_text[:self._index]
        if self.window.bubble.fits_text(self._page_text):
            self.window.bubble.setText(visible, sizing_text=self._page_text)
            return
        head, tail = self.window.bubble.take_page(self._page_text)
        self._type_timer.stop()
        self._pause_timer.stop()
        self._queue.appendleft({"text": tail, "emotion": self.window.avatar_mgr.current_emotion,
                                "action": self._action, "continuation": True})
        self._action = None
        self._page_prefix = ""
        self._current_text = self._page_text = head
        self._index = min(len(visible), len(head))
        self._awaiting_page = False
        self._playing = True
        if not self.window._busy:
            self.window._lock()
            self._stream_done = True
        self.window.bubble.setText(head[:self._index], sizing_text=head)
        self._type_timer.start(self.CHAR_INTERVAL)

    def _play_next(self):
        self._pause_timer.stop()
        if not self._queue:
            self._playing = False
            if self._stream_done:
                self._stream_done = False
                self.window._unlock()
            return
        self._playing = True
        sentence = self._queue[0]
        text = sentence["text"]
        separator = "\n" if self._page_text and not sentence.get("continuation") else ""
        prefix = self._page_text + separator
        if self._awaiting_page:
            prefix = ""
            self._awaiting_page = False
        elif self._page_text and not self.window.bubble.fits_text(prefix + text):
            # Only page changes need reading time; late network chunks count
            # toward it instead of adding another unconditional pause.
            hold_ms = max(1000, min(len(self._page_text) * 35, 6000))
            elapsed_ms = (time.monotonic() - self._page_finished_at) * 1000
            if elapsed_ms < hold_ms:
                self._awaiting_page = True
                self._pause_timer.start(max(1, int(hold_ms - elapsed_ms)))
                return
            prefix = ""
        self._queue.popleft()
        head, tail = self.window.bubble.take_page(text) if not prefix else (text, "")
        if tail:
            self._queue.appendleft(dict(sentence, text=tail, continuation=True))
        self.window.avatar_mgr.set_emotion(sentence.get("emotion", "neutral"))
        self._current_text = head
        self._page_prefix = prefix
        self._page_text = prefix + head
        self._action = sentence.get("action") if not tail else None
        preview = getattr(self.window, "_preview_text", "") if not prefix else ""
        if preview.startswith(head):
            self._index = len(head)
        else:
            self._index = max(2, len(preview)) if head.startswith(preview) else 2
        self._index = min(self._index, len(head))
        self.window._preview_text = ""
        self.window._show_bubble(prefix + head[:self._index], full_text=self._page_text)
        self._type_timer.start(self.CHAR_INTERVAL)

    def _type_next_char(self):
        if not self._type_timer.isActive():
            return
        self._index += max(1, len(self._current_text) // 60)
        self.window.bubble.setText(self._page_prefix + self._current_text[:self._index],
                                   sizing_text=self._page_text)
        if self._index < len(self._current_text):
            return
        self._type_timer.stop()
        self._page_finished_at = time.monotonic()
        if self._action:
            self.window._execute_action_async(self._action)
            self._action = None
        if self._queue:
            self._pause_timer.start(120)
        else:
            # Keep the last page visible; unlock only after explicit stream finish.
            self._play_next()
