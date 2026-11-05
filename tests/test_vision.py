import threading
from types import SimpleNamespace
import pytest
from core.vision import VisionGateway, VisionBusy


def gateway():
    result = object.__new__(VisionGateway)
    result._lock = threading.Lock()
    result.local = SimpleNamespace()
    result.cloud = SimpleNamespace()
    result._retry_local_at = {}
    result._health_until = 0
    result._available_models = set()
    result.foreground_requested = threading.Event()
    result._closed = threading.Event()
    return result


def test_text_and_vision_candidates_use_separate_local_models(monkeypatch):
    import core.vision as module
    service = gateway()
    service.local_available = lambda model=None: True
    monkeypatch.setattr(module, "TEXT_BACKEND", "auto")
    monkeypatch.setattr(module, "VISION_BACKEND", "auto")
    assert list(service.candidates(text=True))[0] == (service.local, module.LOCAL_TEXT_MODEL)
    assert list(service.candidates(text=False))[0] == (service.local, module.OLLAMA_VISION_MODEL)


def test_cached_model_inventory_checks_each_requested_model(monkeypatch):
    import core.vision as module
    service = gateway()
    service._health_until = float("inf")
    service._available_models = {module.LOCAL_TEXT_MODEL}
    assert service.local_available(module.LOCAL_TEXT_MODEL)
    assert not service.local_available(module.OLLAMA_VISION_MODEL)


def test_background_vision_cannot_evict_separate_text_model(monkeypatch):
    import core.vision as module
    service = gateway()
    monkeypatch.setattr(module, "TEXT_BACKEND", "auto")
    monkeypatch.setattr(module, "VISION_BACKEND", "auto")
    monkeypatch.setattr(module, "LOCAL_TEXT_MODEL", "text")
    monkeypatch.setattr(module, "OLLAMA_VISION_MODEL", "vision")
    with pytest.raises(VisionBusy):
        service.complete([], background=True)
    assert not service._lock.locked()


def test_visual_failure_does_not_disable_local_text_model():
    import core.vision as module
    service = gateway()
    service._available_models = {module.LOCAL_TEXT_MODEL, module.OLLAMA_VISION_MODEL}
    service._health_until = float("inf")
    service.failed(service.local, module.OLLAMA_VISION_MODEL)
    assert not service.local_available(module.OLLAMA_VISION_MODEL)
    assert service.local_available(module.LOCAL_TEXT_MODEL)


def test_background_does_not_wait_for_an_occupied_visual_model():
    service = gateway()
    service.acquire(background=True)
    with pytest.raises(VisionBusy):
        service.acquire(background=True)
    service.release()


def test_empty_local_response_falls_back_to_cloud():
    service = gateway()
    service.stream_local = lambda *args, **kw: iter(())
    service.local.chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: SimpleNamespace(choices=[])))
    service.cloud.chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"text":"ok"}'))])))
    service.candidates = lambda: iter([(service.local, "local"), (service.cloud, "cloud")])
    assert service.complete([]) == '{"text":"ok"}'
    assert service._retry_local_at["local"] > 0
    assert not service._lock.locked()


def test_native_stream_applies_residency_context_and_preserves_both_images():
    import httpx
    import json
    from core.metrics import TurnMetrics
    from core.protocol import SENTENCE_SCHEMA
    from config import LOCAL_CONTEXT_TOKENS, LOCAL_KEEP_ALIVE
    service = gateway()
    requests = []
    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, text='{"message":{"content":"hello"}}\n'
                              '{"done":true,"load_duration":1000000,"prompt_eval_duration":2000000,"eval_count":4}\n')
    service.inference = httpx.Client(transport=httpx.MockTransport(respond))
    metrics = TurnMetrics("test")
    messages = [{"role": "user", "content": [
        {"type": "text", "text": "screen then camera"},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,screen"}},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,camera"}}]}]
    assert list(service.stream_local(messages, metrics=metrics, output_format=SENTENCE_SCHEMA)) == ["hello"]
    assert requests[0]["messages"][0]["images"] == ["screen", "camera"]
    assert requests[0]["options"]["num_ctx"] == LOCAL_CONTEXT_TOKENS
    assert requests[0]["keep_alive"] == LOCAL_KEEP_ALIVE
    assert requests[0]["think"] is False
    assert requests[0]["options"]["presence_penalty"] == 0
    assert requests[0]["options"]["top_p"] == 0.8
    assert requests[0]["format"] == SENTENCE_SCHEMA
    assert metrics.values["local_load_duration_ms"] == 1
    service.inference.close()
