"""Explicit opt-in online benchmark; synthetic pictures, no conversation database writes."""
import argparse
import base64
import io
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageDraw
from openai import OpenAI
import httpx
from config import (DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, MODEL, OLLAMA_BASE_URL,
                    LOCAL_TEXT_MODEL, OLLAMA_VISION_MODEL, SYSTEM_PROMPT)
from core.protocol import SentenceParser
from core.transport import cloud_http_client


def run(client, model, picture=None, thinking=None):
    image = [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + picture}}] if picture else []
    prompt = "看看图片，告诉我上面的英文和左侧形状的颜色。" if picture else "今天有点累，不想做事。"
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": [*image, {"type": "text", "text": prompt}]}]
    kwargs = dict(model=model, messages=messages, temperature=0, stream=True, max_tokens=180)
    if thinking is not None:
        if client.base_url.host in {"localhost", "127.0.0.1"}:
            kwargs["extra_body"] = {"reasoning_effort": "none" if not thinking else "low"}
        else:
            kwargs["extra_body"] = {"enable_thinking": thinking}
    started = time.perf_counter()
    result = {"model": model, "image": bool(picture)}
    parser = SentenceParser()
    sentences = []
    try:
        with client.chat.completions.create(**kwargs) as response:
            for chunk in response:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta.content or ""
                if not delta:
                    continue
                result.setdefault("first_token_ms", round((time.perf_counter() - started) * 1000))
                found = parser.feed(delta)
                if found:
                    result.setdefault("first_sentence_ms", round((time.perf_counter() - started) * 1000))
                    sentences.extend(found)
        result.update(total_ms=round((time.perf_counter() - started) * 1000), sentences=sentences)
    except Exception as exc:
        result.update(error=type(exc).__name__, elapsed_ms=round((time.perf_counter() - started) * 1000))
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--local-models", nargs="*", default=[LOCAL_TEXT_MODEL])
    parser.add_argument("--cloud-text", action="store_true")
    parser.add_argument("--local-text", action="store_true")
    parser.add_argument("--repeat", type=int, default=1)
    args = parser.parse_args()
    image = Image.new("RGB", (640, 400), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 80, 220, 280), fill="red")
    draw.text((270, 160), "HELLO", fill="black", font=None, stroke_width=2)
    stream = io.BytesIO()
    image.save(stream, "JPEG", quality=85)
    picture = base64.b64encode(stream.getvalue()).decode()
    results = []
    if args.cloud_text:
        with OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL,
                    http_client=cloud_http_client(40), max_retries=0) as cloud:
            for _ in range(args.repeat):
                results.append(run(cloud, MODEL, thinking=False))
    with OpenAI(api_key="ollama", base_url=OLLAMA_BASE_URL,
                timeout=httpx.Timeout(60, connect=2), max_retries=0) as local:
        for model in args.local_models:
            for _ in range(args.repeat):
                results.append(run(local, model, None if args.local_text else picture,
                                   thinking=False if "qwen3" in model.lower() else None))
    path = Path(__file__).resolve().parents[1] / "data" / "logs" / ("benchmark-" + time.strftime("%Y%m%d-%H%M%S") + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
