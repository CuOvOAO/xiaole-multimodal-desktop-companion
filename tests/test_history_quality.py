from copy import deepcopy
from core.conversation import prepare_prompt_history, material_state_note
from core.context import Interaction
from core.metrics import TurnMetrics
from tests.test_streaming import make_client
from tools.replay_regression import SEED_HISTORY


def test_contaminated_history_is_isolated_without_destroying_original_records():
    history = deepcopy(SEED_HISTORY)
    view = prepare_prompt_history(history, "你能读论文吗？")
    text = str(view)
    assert "苹果派" not in text and "结构和训练" not in text
    assert "你能读论文吗" in text and "总结一下第一篇" in text
    assert history == SEED_HISTORY


def test_valid_material_and_explicit_analogy_are_not_erased():
    history = [{"role": "user", "content": "原文：第一篇论文提出了一种改进方法。"},
               {"role": "assistant", "content": "第一篇论文提出改进方法。"}]
    assert prepare_prompt_history(history, "这篇论文有什么不足") == history
    playful = [{"role": "user", "content": "用苹果派比喻这篇论文，开个玩笑。"},
               {"role": "assistant", "content": "像拆开苹果派一样拆公式。"}]
    assert prepare_prompt_history(playful, "接着玩这个比喻") == playful
    legitimate = [{"role": "user", "content": "帮我拆解公式"}, {"role": "assistant", "content": "把公式拆成两个项分别求导。"}]
    assert prepare_prompt_history(legitimate, "然后呢") == legitimate


def test_user_correction_and_name_survive_work_context():
    client, _ = make_client([])
    client.history = [{"role": "user", "content": "不要叫我老板，我叫小陈"},
                      {"role": "assistant", "content": "好，小陈。"}] + deepcopy(SEED_HISTORY)
    messages, _, _ = client._build_messages(Interaction("论文还没发给你，第一篇写的是什么？"), TurnMetrics("test"))
    text = str(messages)
    assert "小陈" in text and "没有可核验" in text
    assert "苹果派" not in text and "结构和训练方法" not in text
    assert client.history[-1]["content"].endswith("结构和训练方法。")


def test_url_does_not_pretend_document_was_read_and_image_is_a_real_input():
    assert material_state_note([], "总结论文 https://example.com/paper.pdf")
    assert not material_state_note([], "总结这篇论文", has_image=True)


def test_unexecuted_action_turn_does_not_contaminate_history():
    client, _ = make_client(['{"text":"已经打开了","emotion":"happy"}'])
    list(client.chat_stream("帮我打开记事本", record_turn=False))
    assert not client.history
    client.record_tool_turn("帮我打开记事本", "未执行：用户取消了操作。")
    assert client.history[-1]["content"] == "[程序执行反馈] 未执行：用户取消了操作。"
