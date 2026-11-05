from datetime import datetime, timezone, timedelta
import pytest
from core.social import SessionState, build_greeting, departure_intent


class LastChoice:
    @staticmethod
    def choice(values):
        return values[-1]


@pytest.mark.parametrize("text", ["拜拜啦", "小乐拜拜", "我先走啦，明天见", "我去睡觉了", "晚安", "关闭这个界面", "退出程序吧", "把小乐关掉吧", "今天就到这里啦", "我要离开了"])
def test_explicit_departure(text):
    assert departure_intent(text)


@pytest.mark.parametrize("text", ["不要退出", "别关闭这个界面", "他说拜拜啦", "翻译再见", "拜拜是什么意思", "如果我说拜拜，你会怎么样", "关闭浏览器", "关闭摄像头", "教我怎么说再见", "我还没想走", "明天见面聊什么", "台词是「拜拜啦」", "拜拜？"])
def test_mentions_and_other_apps_do_not_close_companion(text):
    assert not departure_intent(text)


@pytest.mark.parametrize("hour,word", [(8, "早"), (12, "中午"), (16, "下午"), (20, "晚上"), (1, "晚")])
def test_greetings_follow_local_time_and_have_something_to_say(hour, word):
    greeting = build_greeting(SessionState(), datetime(2026, 10, 1, hour, tzinfo=timezone(timedelta(hours=8))), LastChoice)
    assert word in greeting.sentences[0]["text"]
    assert len(greeting.sentences) == 2
    assert len(greeting.sentences[1]["text"]) >= 25
    assert not greeting.previous_context


def test_recent_topic_survives_restart_but_expires(tmp_path):
    path = tmp_path / "session.json"
    now = datetime(2026, 10, 1, 20, tzinfo=timezone(timedelta(hours=8)))
    state = SessionState(path)
    state.remember_turn("最近想练习做一个小游戏", "先试试做个跳跃关卡吧。", now.timestamp() - 3600)
    reopened = SessionState(path)
    greeting = build_greeting(reopened, now, LastChoice)
    assert "小游戏" in greeting.sentences[1]["text"]
    assert "跳跃关卡" in greeting.previous_context
    assert reopened.recent_turn(now.timestamp() + 73 * 3600) is None
    assert "小游戏" not in build_greeting(reopened, now + timedelta(days=4), LastChoice).previous_context


def test_opening_topics_do_not_repeat_on_consecutive_launches(tmp_path):
    state = SessionState(tmp_path / "session.json")
    first = build_greeting(state, rng=LastChoice).sentences[1]
    second = build_greeting(SessionState(state.path), rng=LastChoice).sentences[1]
    assert first != second


def test_farewell_and_desktop_commands_do_not_replace_last_topic():
    state = SessionState()
    state.remember_turn("最近想练习做一个小游戏", "先从简单的做起。", 100)
    state.remember_turn("谢谢你今天陪我聊天，拜拜啦", "拜拜", 101)
    state.remember_turn("帮我打开浏览器搜索小游戏", "好", 101)
    assert state.recent_turn(102)["timestamp"] == 100
