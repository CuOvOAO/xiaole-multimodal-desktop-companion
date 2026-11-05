from core.context import Interaction, ObservationStore, capture_intent, reply_style


def test_both_images_have_distinct_sources_and_voice_text():
    parts = Interaction("看看我和屏幕", "asr", "screen", "camera").content()
    assert len([p for p in parts if p["type"] == "image_url"]) == 2
    assert "屏幕" in parts[0]["text"]
    assert "摄像头" in parts[2]["text"]
    assert "语音转写" in parts[-1]["text"]


def test_text_and_asr_keep_distinct_provenance():
    assert Interaction("你好").content().startswith("[文字输入]")
    assert Interaction("你好", "asr").content().startswith("[语音转写]")
    assert Interaction("你好", notes="捕获失败").content().endswith("你好\n捕获失败")


def test_generic_self_reference_does_not_enable_camera():
    assert capture_intent("我现在很累") == (False, False)
    assert capture_intent("看看我和屏幕") == (True, True)
    assert capture_intent("这个呢", "camera") == (False, True)
    assert capture_intent("这个呢", "both") == (True, True)
    assert capture_intent("不要截图") == (False, False)
    assert capture_intent("刚才你说什么", "camera") == (False, False)


def test_observations_expire_and_keep_action_and_vision_separate(monkeypatch):
    monkeypatch.setattr("core.context.time.monotonic", lambda: 100)
    observations = ObservationStore(ttl=10)
    observations.update("red", "screen")
    observations.update("opened", "桌面操作")
    assert "red" in observations.context() and "opened" in observations.context()
    monkeypatch.setattr("core.context.time.monotonic", lambda: 111)
    assert observations.context() == ""


def test_explanations_get_more_output_budget():
    assert reply_style("详细解释一下")[1] > reply_style("你好")[1]
    assert reply_style("别急着给建议，先听我说")[1] > reply_style("你好")[1]


def test_length_follows_explicit_request_not_a_fixed_sentence_count():
    assert reply_style("可以多说一点吗")[1] > reply_style("今天有点失落")[1]
    assert reply_style("只用一句话说说理由")[1] < reply_style("说说理由")[1]
    assert reply_style("别只用一句话，可以多说一点")[1] == 1000
    assert reply_style("我改主意了，只给五分钟")[1] < reply_style("谈谈你的想法")[1]
    assert reply_style("按我们刚定的规则回答")[1] == 450
    assert reply_style("改成五分钟，请详细解释影响")[1] == 1000


def test_history_is_trimmed_in_complete_pairs():
    from core.context import fit_history, estimate_tokens
    history = [{"role": role, "content": text} for text in ("old " * 100, "new") for role in ("user", "assistant")]
    kept = fit_history(history, estimate_tokens("new") * 2)
    assert kept == history[-2:]


def test_cjk_token_estimate_is_not_ascii_character_count_divided_by_four():
    from core.context import estimate_tokens
    assert estimate_tokens("中" * 100) > estimate_tokens("a" * 100)


def test_zero_budget_removes_all_pairs():
    from core.context import fit_history
    assert fit_history([{"role": "user", "content": "u"}, {"role": "assistant", "content": "a"}], 0) == []
