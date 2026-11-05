from types import SimpleNamespace
import threading
from core.context import ObservationStore

from core.llm import LLMClient


class FakeChunkStream:
    def __init__(self, chunks):
        self.chunks = chunks
        self.consumed = 0

    def __iter__(self):
        for content in self.chunks:
            self.consumed += 1
            delta = SimpleNamespace(content=content)
            yield SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


class FakeCompletions:
    def __init__(self, stream):
        self.stream = stream

    def create(self, **_kwargs):
        return iter(self.stream)


def make_client(chunks):
    client = object.__new__(LLMClient)
    stream = FakeChunkStream(chunks)
    client.client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions(stream))
    )
    client._ollama_client = None
    client._ollama_ok = False
    client.memory_service = None
    client._history_lock = threading.Lock()
    client.observations = ObservationStore()
    client.history = []
    return client, stream


def test_first_ndjson_sentence_yields_before_stream_finishes():
    client, source = make_client([
        '{"text":"第一',
        '句","emotion":"happy"}\n',
        '{"text":"第二句","emotion":"neutral"}',
    ])

    output = client.chat_stream("测试")
    first = next(output)

    assert first == {"text": "第一句", "emotion": "happy"}
    assert source.consumed == 2
    assert list(output) == [{"text": "第二句", "emotion": "neutral"}]


def test_legacy_sentences_wrapper_still_falls_back():
    raw = '{"sentences":[{"text":"旧格式","emotion":"sad"}]}'
    client, _ = make_client([raw])
    assert list(client.chat_stream("测试")) == [
        {"text": "旧格式", "emotion": "sad"}
    ]


def test_malformed_closed_object_does_not_block_next_object():
    client, _ = make_client([
        '{bad json}\n{"text":"恢复成功","emotion":"neutral"}'
    ])
    assert list(client.chat_stream("测试"))[0]["text"] == "恢复成功"


def test_nested_action_and_braces_inside_string():
    raw = (
        '{"text":"查看 {结果}","emotion":"thinking",'
        '"action":{"type":"search","query":"蕾缪乐"}}'
    )
    obj, end = LLMClient._try_extract_json(raw)
    assert end == len(raw)
    assert obj["action"]["type"] == "search"


def test_failed_request_never_appends_unanswered_user_turn():
    client, _ = make_client(['{"bad":true}'])
    import pytest
    with pytest.raises(ValueError):
        list(client.chat_stream("test"))
    assert client.history == []


def test_successful_history_does_not_retain_actions():
    client, _ = make_client(['{"text":"done","action":{"type":"open","target":"notepad"}}'])
    list(client.chat_stream("open"))
    assert client.history[-1]["content"] == "done"


def test_usage_only_chunk_is_ignored():
    client, _ = make_client(['{"text":"done"}'])
    base_create = client.client.chat.completions.create
    def create(**kwargs):
        yield SimpleNamespace(choices=[])
        yield from base_create(**kwargs)
    client.client.chat.completions.create = create
    assert list(client.chat_stream("test"))[0]["text"] == "done"


def test_plain_reply_preview_arrives_before_final_fallback():
    client, _ = make_client(["老板，", "我有点不同意见。"])
    previews = []
    sentences = list(client.chat_stream("test", preview_callback=previews.append))
    assert previews == ["老板，", "老板，我有点不同意见。"]
    assert sentences[0]["text"] == previews[-1]


def test_paragraph_preview_is_not_cut_at_old_130_character_limit():
    import json
    paragraph = "这个意思还需要说完整。" * 20
    raw = json.dumps({"sentences": [{"text": paragraph, "emotion": "thinking"}]}, ensure_ascii=False)
    client, _ = make_client([raw[:-5], raw[-5:]])
    previews = []
    output = list(client.chat_stream("展开说说", preview_callback=previews.append))
    assert previews[0] == paragraph
    assert output[0]["text"] == paragraph


def test_local_schema_allows_more_than_three_units_without_mutation():
    from core.protocol import SENTENCE_SCHEMA
    client, _ = make_client([])
    recorded = []
    local = object()
    def stream(*args, **kwargs):
        recorded.append(kwargs["output_format"])
        return iter(['{"sentences":[{"text":"说完一个意思。","emotion":"neutral"}]}'])
    client.vision = SimpleNamespace(local=local, foreground_requested=threading.Event(),
        acquire=lambda **kw: None, release=lambda: None,
        candidates=lambda **kw: [(local, "qwen3:8b")], stream_local=stream)
    assert list(client.chat_stream("聊聊这件事"))
    assert recorded[0]["properties"]["sentences"]["maxItems"] == 12
    assert recorded[0] == SENTENCE_SCHEMA


def test_exhausted_local_only_candidates_cannot_report_empty_success():
    import pytest
    client, _ = make_client([])
    local = object()
    client.vision = SimpleNamespace(local=local, foreground_requested=threading.Event(),
        acquire=lambda **kw: None, release=lambda: None, failed=lambda *args: None,
        candidates=lambda **kw: [(local, "qwen3:8b")], stream_local=lambda *args, **kw: iter(()))
    with pytest.raises(ValueError):
        list(client.chat_stream("你好"))
    assert not client.history

