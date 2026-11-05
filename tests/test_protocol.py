from core.protocol import SentenceParser, normalize_sentence, parse_response


def test_wrapped_sentence_yields_without_wrapper_closing():
    parser = SentenceParser()
    assert parser.feed('{"sentences":[{"text":"first","emotion":"happy"}') == [{"text": "first", "emotion": "happy"}]
    assert parser.feed(',{"text":"second"}]}')[0]["text"] == "second"


def test_nested_action_text_is_not_emitted_as_dialogue():
    parser = SentenceParser()
    result = parser.feed('{"text":"done","action":{"type":"type","text":"secret"}}')
    assert len(result) == 1 and result[0]["text"] == "done"


def test_escape_split_across_chunks_and_unknown_emotion():
    parser = SentenceParser()
    assert not parser.feed('{"text":"quote \\')
    assert parser.feed('" and {brace}","emotion":[]}')[0]["emotion"] == "neutral"


def test_invalid_json_is_not_shown_raw_and_null_is_silent():
    assert parse_response('{"text": "broken" nope}') == {"sentences": []}
    assert parse_response("null") == {"sentences": []}
    assert normalize_sentence({"text": 1}) is None


def test_preview_decodes_text_without_json_or_action():
    parser = SentenceParser()
    parser.feed('{"text":"hello \\u4e')
    assert parser.preview() == "hello "
    parser.feed('50","action":{"type":"open"}}')
    assert parser.preview() == "hello 乐"


def test_action_first_does_not_expose_typed_content_in_preview():
    parser = SentenceParser()
    result = parser.feed('{"action":{"data":{"text":"secret"}},"text":"done"}')
    assert result == [{"text": "done", "emotion": "neutral", "action": {"data": {"text": "secret"}}}]
    assert parser.preview() == ""


def test_plain_reply_can_preview_without_waiting_for_end():
    parser = SentenceParser()
    parser.feed("这句")
    assert parser.preview() == "这句"
    parser.feed("我收下了。")
    assert parser.preview() == "这句我收下了。"
    for raw in ('{"te', "```json", "nu", "null", "<think>secret"):
        other = SentenceParser()
        other.feed(raw)
        assert other.preview() == ""
