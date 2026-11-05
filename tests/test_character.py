from core.character import CharacterGuide
from core.context import Interaction
from core.metrics import TurnMetrics
from tests.test_streaming import make_client


def test_character_sources_exist_and_examples_are_not_current_history():
    guide = CharacterGuide()
    sources = {line["source"] for line in guide.lines}
    assert set(guide.profile["sources"]) <= sources
    for scene in guide.profile["scenes"]:
        assert set(scene["sources"]) <= sources
        assert scene["example"]["reply"] not in guide.identity()
    assert "场景改写示例" not in guide.context("随便聊两句")


def test_persona_is_available_without_memory_and_system_prefix_is_stable():
    client, _ = make_client([])
    first, _, _ = client._build_messages(Interaction("今天有点累"), TurnMetrics("test"))
    client.observations.update("测试画面", "screen")
    second, _, _ = client._build_messages(Interaction("随便聊点吧"), TurnMetrics("test"))
    assert first[0]["content"].split("【本轮表达要求】")[0] == second[0]["content"].split("【本轮表达要求】")[0]
    assert "本轮相处方式" in first[0]["content"]
    assert "相处方式" in first[0]["content"]
    assert "测试画面" in second[-1]["content"]
    assert "今天有点累" in first[-1]["content"]
    assert not client.history


def test_raw_lore_is_not_used_for_generic_chitchat():
    from core.context import character_fact_intent
    guide = CharacterGuide()
    assert not character_fact_intent("随便聊点吧")
    assert character_fact_intent("你的姐姐怎么了")
    assert "原有资料节选" not in guide.context("随便聊点吧")
    assert "冰淇淋" not in guide.context("随便聊点吧")


def test_factual_grounding_is_turn_specific_and_not_a_character_gimmick():
    from core.context import grounding_guidance
    client, _ = make_client([])
    messages, _, _ = client._build_messages(Interaction("你能看懂论文里的公式吗？"), TurnMetrics("test"))
    assert "材料未提供时" in messages[0]["content"]
    assert "喜欢把东西拆开" not in messages[0]["content"]
    assert "苹果派" not in messages[0]["content"]
    assert not grounding_guidance("先不看论文了，你别急着给建议，就聊聊这种感觉。")
    assert not grounding_guidance("今天想聊点什么？")


def test_listening_request_does_not_turn_into_instructions_or_promises():
    from core.context import reply_style
    style, _ = reply_style("你别急着给建议，就聊聊这种感觉。")
    assert "不提供解决步骤" in style and "不承诺" in style
