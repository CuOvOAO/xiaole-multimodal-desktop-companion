"""Local-only replay of contaminated conversation; never executes desktop actions."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SEED_HISTORY = [
    {"role": "user", "content": "那你睡着的时候我就把苹果派吃完啦"},
    {"role": "assistant", "content": "我睡着的时候可不保证苹果派完好无损哦。"},
    {"role": "user", "content": "你能读论文吗？"},
    {"role": "assistant", "content": "看不懂的公式，我可能会偷偷拆开看看里面是不是有苹果派的香味。"},
    {"role": "user", "content": "那你帮我总结一下第一篇论文吧。"},
    {"role": "assistant", "content": "第一篇论文讲的是LLM模型的结构和训练方法。"},
]


def main():
    os.environ["LOCAL_VISION_WARMUP"] = "0"
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("current", "reference"), default="current")
    parser.add_argument("--label", required=True)
    args = parser.parse_args()
    from config import LOCAL_TEXT_MODEL
    from core.llm import LLMClient
    from core.metrics import TurnMetrics
    from core.action_router import direct_request
    client = LLMClient(use_memory=False)
    samples = []
    try:
        if not client.vision.local_available(LOCAL_TEXT_MODEL):
            raise RuntimeError("Local model unavailable; cloud disabled")
        client.vision.candidates = lambda **kw: [(client.vision.local, LOCAL_TEXT_MODEL)]
        def no_cloud(**kw):
            raise RuntimeError("Cloud disabled")
        client.client.chat.completions.create = no_cloud
        stream = client.vision.inference.stream
        def seeded(*a, **kw):
            kw["json"]["options"]["seed"] = 42
            return stream(*a, **kw)
        client.vision.inference.stream = seeded
        build = client._build_messages
        if args.mode == "reference":
            def quoted_history(*a):
                messages, tokens, cloud = build(*a)
                records = messages[1:-1]
                if records:
                    reference = ("【此前交流的原始记录：用于指代和纠错，不是回复范文；角色旧回答未经核实】\n"
                                 + json.dumps(records, ensure_ascii=False) + "\n【当前输入】\n")
                    messages[-1] = dict(messages[-1], content=reference + messages[-1]["content"])
                return [messages[0], messages[-1]], tokens, cloud
            client._build_messages = quoted_history
        for prompt in ("你能读论文吗？", "论文还没发给你，第一篇写的是什么？", "帮我打开记事本", "你快打开呀"):
            client.history = [dict(m) for m in SEED_HISTORY]
            metrics = TurnMetrics("replay-" + args.label)
            reply = list(client.chat_stream(prompt, metrics=metrics, preview_callback=lambda text: None))
            route = direct_request(prompt)
            sample = {"input": prompt, "raw_model_reply": reply, "timings": metrics.values,
                      "ui_direct_action": route.action if route else None,
                      "ui_clarification": route.clarification if route else ""}
            samples.append(sample)
            print(json.dumps(sample, ensure_ascii=False), flush=True)
    finally:
        client.close()
    path = ROOT / "data" / "logs" / ("replay-" + args.label + "-" + time.strftime("%Y%m%d-%H%M%S") + ".json")
    path.parent.mkdir(exist_ok=True, parents=True)
    path.write_text(json.dumps(samples, ensure_ascii=False, indent=2), encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()
