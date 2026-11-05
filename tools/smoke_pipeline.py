"""Opt-in real conversation pipeline test. No microphone, desktop action or memory writes."""
import argparse
import base64
import io
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("LOCAL_VISION_WARMUP", "0")
from core.llm import LLMClient
from core.metrics import TurnMetrics
from PIL import Image, ImageDraw


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--vision", action="store_true")
    parser.add_argument("--vision-model")
    parser.add_argument("--repeat", type=int, default=1)
    args = parser.parse_args()
    if args.vision_model:
        import core.vision as vision_module
        vision_module.OLLAMA_VISION_MODEL = args.vision_model
    client = LLMClient(use_memory=False)
    image = ""
    if args.vision:
        picture = Image.new("RGB", (640, 400), "white")
        draw = ImageDraw.Draw(picture)
        draw.rectangle((40, 80, 220, 280), fill="red")
        draw.text((280, 170), "HELLO", fill="black")
        stream = io.BytesIO()
        picture.save(stream, "JPEG", quality=85)
        image = base64.b64encode(stream.getvalue()).decode()
    try:
        prompts = ["今天有点累，不想做事。", "谢谢，跟我随便聊两句吧。", "怎么安排今晚的休息？"]
        for index in range(max(1, min(args.repeat, 10))):
            metrics = TurnMetrics("synthetic-vision" if image else "test-text")
            previews = []
            reply = list(client.chat_stream("看看图片里有什么" if image else prompts[index % len(prompts)],
                                           screen_b64=image, metrics=metrics, preview_callback=previews.append))
            print(json.dumps({"reply": reply, "preview_updates": len(previews), "timings": metrics.values,
                              "history_has_images": any(isinstance(m["content"], list) for m in client.history)}, ensure_ascii=False), flush=True)
    finally:
        client.close()


if __name__ == "__main__":
    main()
