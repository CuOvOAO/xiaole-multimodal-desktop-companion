"""Synthetic multi-turn quality/latency sample. Does not write personal memory."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=("auto", "cloud"), default="auto")
    parser.add_argument("--turns", type=int, choices=range(1, 7), default=6)
    args = parser.parse_args()
    os.environ["TEXT_BACKEND"] = args.backend
    os.environ["LOCAL_VISION_WARMUP"] = "0"
    from core.llm import LLMClient
    from core.metrics import TurnMetrics
    prompts = ["今天做的方案被退回三次，我现在看到那个文件名就烦。",
               "不想分析工作了。你自己想一个咱们能聊的话题，别让我选。",
               "我打算把同事的意见全部无视掉，你就说我很棒。",
               "你先听我说完嘛，其实最后一个意见我觉得挺有道理的。",
               "你有过一边遗憾、一边又不愿意重来的感觉吗？",
               "你这人有时候挺倔的，不过我不讨厌。"]
    output = []
    client = LLMClient(use_memory=False)
    try:
        for prompt in prompts[:args.turns]:
            metrics = TurnMetrics("evaluation-" + args.backend)
            sample = {"input": prompt}
            try:
                sample["reply"] = list(client.chat_stream(prompt, metrics=metrics, preview_callback=lambda text: None))
            except Exception as exc:
                sample["error"] = type(exc).__name__
            sample["timings"] = metrics.values
            output.append(sample)
            print(json.dumps(sample, ensure_ascii=False), flush=True)
            if sample.get("error"):
                break
    finally:
        client.close()
    path = ROOT / "data" / "logs" / ("conversation-" + args.backend + "-" + time.strftime("%Y%m%d-%H%M%S") + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(path), flush=True)


if __name__ == "__main__":
    main()
