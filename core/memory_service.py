"""Bounded memory work, latency budgets, and a durable pending-turn journal."""
import json
import logging
import os
from pathlib import Path
import queue
import threading
import time
from uuid import uuid4
from concurrent.futures import Future, TimeoutError


class MemoryService:
    def __init__(self, factory=None, journal_path=None):
        self.manager = None
        self.ready = threading.Event()
        self.failed = threading.Event()
        self._queue = queue.Queue(maxsize=64)
        self._cache = {}
        self._cache_lock = threading.Lock()
        self._journal_lock = threading.Lock()
        self._pending = {}
        self._queued = set()
        self._journal = Path(journal_path) if journal_path else (
            Path(__file__).resolve().parents[1] / "data" / "memory_pending.json" if factory is None else None)
        if self._journal and self._journal.exists():
            try:
                records = json.loads(self._journal.read_text(encoding="utf-8"))["records"]
                self._pending = {record["id"]: record for record in records}
            except (OSError, ValueError, KeyError, TypeError):
                # Preserve a damaged journal rather than silently overwriting user history.
                self.failed.set()
                logging.error("Memory journal cannot be read; memory disabled until journal is repaired")
        self._closed = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(factory,), daemon=True)
        self._thread.start()

    def _write_journal(self):
        if self._journal is None:
            return
        self._journal.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._journal.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump({"version": 1, "records": list(self._pending.values())}, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(self._journal)

    def _take_pending(self):
        with self._journal_lock:
            for record in self._pending.values():
                if record["id"] not in self._queued:
                    self._queued.add(record["id"])
                    return ("save", (record["user"], record["reply"], record["emotion"], record["id"]), None)
        return None

    def _run(self, factory):
        if self.failed.is_set():
            return
        try:
            warmup = factory is None
            if factory is None:
                os.environ.setdefault("OMP_NUM_THREADS", "2")
                os.environ.setdefault("MKL_NUM_THREADS", "2")
                os.environ.setdefault("HF_HUB_OFFLINE", os.getenv("EMBEDDING_LOCAL_ONLY", "1"))
                from core.memory import MemoryManager
                factory = MemoryManager
            manager = factory()
            if not getattr(manager, "enabled", True):
                raise RuntimeError("Memory dependency unavailable")
            if warmup:
                manager.retrieve_combined("角色身份")
            self.manager = manager
            self.ready.set()
            logging.info("Memory ready; retrieval and persistence run in one daemon")
            while not self._closed.is_set() or not self._queue.empty():
                from_queue = True
                try:
                    job = self._queue.get(timeout=0.2)
                except queue.Empty:
                    if self._closed.is_set():
                        break
                    job = self._take_pending()
                    from_queue = False
                    if job is None:
                        continue
                kind, args, future = job
                try:
                    if kind == "retrieve":
                        future.set_result(manager.retrieve_combined(args[0], **args[1]))
                    else:
                        manager.save_turn(*args)
                        with self._journal_lock:
                            self._pending.pop(args[3], None)
                            self._queued.discard(args[3])
                            self._write_journal()
                except Exception as exc:
                    logging.warning("Memory %s failed: %s", kind, type(exc).__name__)
                    if future:
                        future.set_result("")
                    if kind == "save":
                        with self._journal_lock:
                            self._queued.discard(args[3])
                        time.sleep(1)
                finally:
                    if from_queue:
                        self._queue.task_done()
        except Exception as exc:
            self.failed.set()
            logging.warning("Memory unavailable: %s", type(exc).__name__)

    def prefetch(self, text, **options):
        if self.manager is None or self._closed.is_set() or self.failed.is_set():
            return None
        with self._cache_lock:
            now = time.monotonic()
            key = (text, tuple(sorted(options.items())))
            cached = self._cache.get(key)
            if cached and now - cached[0] < 60:
                return cached[1]
            future = Future()
            try:
                self._queue.put_nowait(("retrieve", (text, options), future))
            except queue.Full:
                return None
            self._cache = {key: value for key, value in self._cache.items() if now - value[0] < 60}
            self._cache[key] = (now, future)
            return future

    def retrieve(self, text, budget=0.15, **options):
        future = self.prefetch(text, **options)
        if future is None:
            return ""
        try:
            return future.result(timeout=budget)
        except TimeoutError:
            return ""

    def save(self, user, reply, emotion):
        if self._closed.is_set() or self.failed.is_set():
            return
        turn_id = uuid4().hex
        with self._journal_lock:
            if len(self._pending) >= 128:
                logging.error("Memory pending journal full; turn not persisted")
                return
            self._pending[turn_id] = {"id": turn_id, "user": user, "reply": reply, "emotion": emotion}
            # Journal first: exiting during model warmup must not lose the completed conversation.
            self._write_journal()
            try:
                self._queue.put_nowait(("save", (user, reply, emotion, turn_id), None))
                self._queued.add(turn_id)
            except queue.Full:
                pass  # The daemon drains journal records when the queue becomes idle.
        with self._cache_lock:
            self._cache.clear()

    def close(self):
        self._closed.set()
        self._thread.join(timeout=0.3)
