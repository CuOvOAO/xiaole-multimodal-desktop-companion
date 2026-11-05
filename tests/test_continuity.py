from types import SimpleNamespace
from core.context import Interaction
from core.conversation import retrieval_plan, select_dialogue, message_cost
from core.metrics import TurnMetrics
from core.social import SessionState
from tests.test_streaming import make_client


def pair(user, reply):
    return [{"role": "user", "content": user}, {"role": "assistant", "content": reply}]


def test_plain_followups_do_not_retrieve_unrelated_archive():
    history = pair("室友总改时间", "你介意的是时间被打乱？")
    for text in ("对，就是这样", "我刚才说的是室友，不是我", "那你觉得呢？", "换个话题吧"):
        assert retrieval_plan(text, history) is None
    plan = retrieval_plan("上次说的那个还记得吗？", history)
    assert "室友总改时间" in plan.query
    assert plan.conversations and not plan.character
    assert plan.exclude_users == ("室友总改时间",)
    plan = retrieval_plan("你的姐姐是谁？", history)
    assert plan.character and not plan.conversations


def test_old_memory_cannot_displace_recent_complete_turns():
    client, _ = make_client([])
    client.history = sum((pair("最近第%d轮的安排" % n, "回应第%d轮" % n) for n in range(4)), [])
    calls = []
    def retrieve(*args, **kwargs):
        calls.append(kwargs)
        return "无关旧事" * 3000
    client.memory_service = SimpleNamespace(retrieve=retrieve)
    metrics = TurnMetrics("test")
    messages, _, force_cloud = client._build_messages(Interaction("上次说的安排呢？"), metrics)
    assert messages[1:-1] == client.history
    assert "无关旧事" not in messages[-1]["content"]
    assert calls[0]["exclude_users"] == tuple(m["content"] for m in client.history if m["role"] == "user")
    assert not force_cloud
    assert metrics.values["history_turns_sent"] == 4


def test_older_correction_keeps_speaker_order_without_separating_recent_pairs():
    history = pair("更正一下，约好的是周日，不是周六。", "好，是周日。")
    history += sum((pair("今天的测试内容第%d段。" % n, "我在认真听你继续说。") for n in range(12)), [])
    budget = message_cost(history[-8:]) + 220
    kept, earlier = select_dialogue(history, budget)
    assert kept[-8:] == history[-8:]
    assert kept[0]["role"] == "user"
    assert "老板：更正一下，约好的是周日，不是周六。" in earlier
    assert "你：好，是周日。" in earlier
    from core.context import estimate_tokens
    assert message_cost(kept) + estimate_tokens(earlier) <= budget


def test_greeting_and_spontaneous_speech_remain_addressable_after_first_reply():
    client, _ = make_client([])
    client.set_opening("我想给闹钟加个讨价还价的功能。")
    client.set_opening("我想给闹钟加个讨价还价的功能。")
    client._post_process_sentences("最多延后一次", "", [{"text": "那就一次。", "emotion": "happy"}])
    client.record_utterance("你把窗口换成深色了啊。")
    messages, _, _ = client._build_messages(Interaction("你先前那个点子呢？"), TurnMetrics("test"))
    contents = [m["content"] for m in messages]
    assert contents.count("我想给闹钟加个讨价还价的功能。") == 1
    assert "你把窗口换成深色了啊。" in contents


def test_restart_restores_sequence_including_short_correction_and_expires(tmp_path):
    path = tmp_path / "session.json"
    state = SessionState(path)
    state.remember_turn("闹钟最多延后十分钟", "那就十分钟。", 100)
    state.remember_turn("改成五分钟", "五分钟，还是只能一次。", 101)
    state.remember_turn("嗯", "那就这么定。", 102)
    reopened = SessionState(path)
    history = reopened.recent_history(110)
    assert len(history) == 6
    assert history[2]["content"].endswith("改成五分钟")
    assert history[4]["content"].endswith("嗯")
    plan = retrieval_plan("上次说的什么？", history)
    assert "改成五分钟" in plan.exclude_users
    assert reopened.recent_history(102 + 73 * 3600) == []


def test_archive_selection_excludes_live_turns_and_keeps_provenance():
    # Bypass the database/embedding constructor; exercise the actual selection logic.
    from core.memory import MemoryManager
    class Collection:
        def count(self):
            return 3

        def query(self, **kwargs):
            return {"documents": [["duplicate", "older", "newer"]], "distances": [[.1, .2, .25]],
                    "metadatas": [[
                        {"user": "刚刚说过", "assistant": "不能再召回", "timestamp": 100},
                        {"user": "以前约周六", "assistant": "猜测", "timestamp": 101},
                        {"user": "后来改周日", "assistant": "回应", "timestamp": 102},
                    ]]}
    manager = object.__new__(MemoryManager)
    manager.enabled = True
    manager.conv_col, manager.char_col = Collection(), Collection()
    manager.ef = lambda texts: [[0.0]]
    result = manager.retrieve_combined("以前的约定", include_character=False, exclude_users=("刚刚说过",))
    assert "刚刚说过" not in result
    assert result.index("以前约周六") < result.index("后来改周日")
    assert "角色当时的回答（不是已确认事实）：猜测" in result
    assert "时间：" in result


def test_constraints_keep_user_corrections_not_assistant_inventions_and_follow_topic():
    from core.conversation import user_constraints
    history = pair("最多延后一次", "我帮你按掉五次") + pair("改成五分钟", "明白")
    context = user_constraints(history, "那第二次呢？")
    assert "最多延后一次" in context and "改成五分钟" in context
    assert "按掉五次" not in context
    assert user_constraints(history, "换个话题，聊聊做饭") == ""
    history += pair("换个话题，今晚不要煮面", "好")
    context = user_constraints(history, "你觉得呢？")
    assert "不要煮面" in context and "五分钟" not in context


def test_previous_single_turn_state_is_migrated_without_duplicate(tmp_path):
    import json
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps({"turn": {"user": "old", "reply": "answer", "timestamp": 100}}))
    state = SessionState(path)
    assert len(state.recent_history(101)) == 2
    state.remember_turn("改了", "好", 102)
    assert len(SessionState(path).recent_history(103)) == 4
