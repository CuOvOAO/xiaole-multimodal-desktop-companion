# test_v5.py — V5 核心逻辑测试
import sys
sys.path.insert(0, ".")

from core.llm import LLMClient

# 测试 _try_extract_json
print("=== _try_extract_json 测试 ===")

# 1. 简单句子
obj, pos = LLMClient._try_extract_json('{"text": "hello", "emotion": "happy"}')
assert obj == {"text": "hello", "emotion": "happy"}
print(f"1. 简单句子 OK: {obj}")

# 2. 嵌套 action
obj, pos = LLMClient._try_extract_json(
    '{"text": "ok", "emotion": "happy", "action": {"type": "search", "query": "test"}}'
)
assert obj["action"]["type"] == "search"
print(f"2. 嵌套 action OK: {obj}")

# 3. 前面有垃圾文本
obj, pos = LLMClient._try_extract_json(
    'some garbage {"text": "found", "emotion": "neutral"} more stuff'
)
assert obj["text"] == "found"
print(f"3. 前有垃圾 OK: {obj}, pos={pos}")

# 4. 不完整 JSON
obj, pos = LLMClient._try_extract_json('{"text": "incompl')
assert obj is None
print(f"4. 不完整 OK: None")

# 5. 空缓冲
obj, pos = LLMClient._try_extract_json("")
assert obj is None
print(f"5. 空缓冲 OK: None")

# 6. 多个对象，只提取第一个
buf = '{"text": "a", "emotion": "happy"}, {"text": "b", "emotion": "sad"}'
obj, pos = LLMClient._try_extract_json(buf)
assert obj["text"] == "a"
remaining = buf[pos:].lstrip(" ,\n\r\t")
obj2, _ = LLMClient._try_extract_json(remaining)
assert obj2["text"] == "b"
print(f"6. 多对象连续提取 OK: first={obj}, second={obj2}")

# 7. 字符串内含花括号
obj, pos = LLMClient._try_extract_json('{"text": "hello {world}", "emotion": "happy"}')
assert obj["text"] == "hello {world}"
print(f"7. 字符串内花括号 OK: {obj}")

# 测试 Ollama 检测
client = LLMClient(use_memory=False)
try:
    print(f"\nLocal model available: {client.vision.local_available()}")
finally:
    client.close()

# 测试 parse_response 向后兼容
r = LLMClient.parse_response('{"sentences": [{"text": "hi", "emotion": "happy"}]}')
assert r["sentences"][0]["text"] == "hi"
print(f"parse_response sentences OK")

r = LLMClient.parse_response('{"text": "old", "emotion": "sad"}')
assert r["sentences"][0]["text"] == "old"
print(f"parse_response old format OK")

print("\n=== ALL V5 TESTS PASSED ===")
