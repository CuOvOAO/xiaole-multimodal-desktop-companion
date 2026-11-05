import threading
import time
from core.memory_service import MemoryService


def test_slow_memory_has_budget_and_late_result_is_reused():
    called = []
    class Manager:
        def retrieve_combined(self, text):
            called.append(text)
            time.sleep(0.12)
            return "found"
        def save_turn(self, *args):
            pass
    service = MemoryService(Manager)
    while service.manager is None:
        time.sleep(0.001)
    start = time.monotonic()
    assert service.retrieve("query", budget=0.01) == ""
    assert time.monotonic() - start < 0.1
    time.sleep(0.15)
    assert service.retrieve("query", budget=0.01) == "found"
    assert called == ["query"]
    service.close()


def test_memory_save_does_not_block_generation():
    saved = threading.Event()
    class Manager:
        def save_turn(self, *args):
            time.sleep(0.05)
            saved.set()
    service = MemoryService(Manager)
    service.save("u", "a", "neutral")
    assert saved.wait(1)
    service.close()


def test_journal_is_replayed_with_stable_ids(tmp_path):
    import json
    journal = tmp_path / "pending.json"
    journal.write_text(json.dumps({"records": [{"id": "stable", "user": "u", "reply": "a", "emotion": "neutral"}]}))
    saved = threading.Event()
    ids = []
    class Manager:
        def save_turn(self, user, reply, emotion, turn_id):
            ids.append(turn_id)
            saved.set()
    service = MemoryService(Manager, journal_path=journal)
    assert saved.wait(2)
    service.close()
    assert ids == ["stable"]
    assert json.loads(journal.read_text())["records"] == []


def test_completed_turn_is_durable_before_embedding_initializes(tmp_path):
    import json
    release = threading.Event()
    def unavailable():
        release.wait(1)
        raise RuntimeError("unavailable")
    journal = tmp_path / "pending.json"
    service = MemoryService(unavailable, journal_path=journal)
    service.save("user", "reply", "neutral")
    assert json.loads(journal.read_text())["records"][0]["reply"] == "reply"
    service.close()
    release.set()


def test_bad_journal_is_not_overwritten(tmp_path):
    journal = tmp_path / "pending.json"
    journal.write_text("broken")
    service = MemoryService(lambda: object(), journal_path=journal)
    service.save("u", "a", "neutral")
    assert journal.read_text() == "broken"
    service.close()


def test_retrieval_cache_is_scoped_to_current_conversation_and_intent():
    calls = []
    class Manager:
        def retrieve_combined(self, text, **options):
            calls.append(options)
            return str(options)
    service = MemoryService(Manager)
    assert service.ready.wait(1)
    try:
        first = service.retrieve("之前那个", 1, exclude_users=("old",), include_conversations=True)
        assert first == service.retrieve("之前那个", 1, exclude_users=("old",), include_conversations=True)
        second = service.retrieve("之前那个", 1, exclude_users=("new",), include_conversations=True)
        assert first != second
        assert len(calls) == 2
    finally:
        service.close()
