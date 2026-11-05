# test_v4.py — V4 改动导入+逻辑验证
import sys
sys.path.insert(0, ".")

from config import SYSTEM_PROMPT, SCREEN_WATCH_PROMPT, VISION_MODEL
print("config OK, VISION_MODEL:", VISION_MODEL)
print("SCREEN_WATCH_PROMPT defined:", bool(SCREEN_WATCH_PROMPT))

from core.llm import LLMClient

# 测试 parse_response: sentences 格式
r1 = LLMClient.parse_response('{"sentences": [{"text": "hello", "emotion": "happy"}]}')
assert "sentences" in r1 and r1["sentences"][0]["text"] == "hello"
print("sentences format OK:", r1)

# 测试 parse_response: 旧格式转换
r2 = LLMClient.parse_response('{"text": "old format", "emotion": "sad"}')
assert "sentences" in r2
print("old format converted OK:", r2)

# 测试 parse_response: 旧格式 + action（action 应在最后一句）
r3 = LLMClient.parse_response(
    '{"text": "hello!world!", "emotion": "happy", "action": {"type": "open", "target": "notepad"}}'
)
assert r3["sentences"][-1].get("action") is not None
print("old format + action OK:", r3)

# 测试 parse_response: 带嵌套花括号的完整 JSON
r4 = LLMClient.parse_response(
    '{"sentences": [{"text": "ok!", "emotion": "happy", "action": {"type": "search", "query": "test", "engine": "google"}}]}'
)
assert r4["sentences"][0]["action"]["type"] == "search"
print("nested action OK:", r4)

# 测试 parse_response: 解析失败 fallback
r5 = LLMClient.parse_response("this is not json at all")
assert r5["sentences"][0]["text"] == "this is not json at all"
print("fallback OK:", r5)

from core.screen_watcher import ScreenWatcher
print("screen_watcher import OK")

from core.desktop import HumanLikeController
print("desktop import OK")

print("\n=== ALL V4 TESTS PASSED ===")
