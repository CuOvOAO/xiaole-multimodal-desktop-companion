import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from core.llm import LLMClient

client = LLMClient(use_memory=False)
try:
    result = client.chat("你好呀！")
    for sentence in result.get("sentences", []):
        print("文本:", sentence.get("text", ""))
        print("情绪:", sentence.get("emotion", "neutral"))
finally:
    client.close()
