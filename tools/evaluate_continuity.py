"""Synthetic local-only conversation checks; never reads or writes personal memory."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CASES = {
    "correction": [
        "周六我要帮室友阿禾搬书，不是我要搬家。先别给清单，听我说说。",
        "更正一下，是周日，他周六要加班。",
        "箱子已经借好了。我烦的是他总临时改时间，不是担心书装不下。",
        "那你觉得我真正介意的是什么？",
        "他刚又说不用我去了，我反而有点失落。",
        "你觉得这和我刚才烦他矛盾吗？别泛泛安慰，结合这件事说。",
    ],
    "reference": [
        "你刚才那个闹钟点子，我选讨价还价，不过最多延后一次。",
        "我说的是闹钟，不是真人。延后十分钟就必须起床。",
        "我改主意了，只给五分钟，十分钟太容易迟到。",
        "它第二次求我再睡会儿呢？按我们刚定的规则回答。",
        "换个话题，我最近学做饭，总把面条煮得太软。",
        "我是想留一点嚼劲，不是夹生。你明白这两个的区别吧？",
    ],
}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="after")
    parser.add_argument("--case", choices=list(CASES))
    parser.add_argument("--presence-penalty", type=float)
    parser.add_argument("--structured-history", action="store_true", help="Diagnostic: match assistant history to the output protocol")
    args = parser.parse_args()
    os.environ["TEXT_BACKEND"] = "auto"
    os.environ["LOCAL_VISION_WARMUP"] = "0"
    if args.presence_penalty is not None:
        os.environ["LOCAL_PRESENCE_PENALTY"] = str(args.presence_penalty)
    from core.llm import LLMClient
    from core.metrics import TurnMetrics

    output = []
    for name, prompts in CASES.items():
        if args.case and name != args.case:
            continue
        client = LLMClient(use_memory=False)
        try:
            if args.structured_history:
                build_messages = client._build_messages
                def structured_messages(*positional):
                    messages, budget, force_cloud = build_messages(*positional)
                    for message in messages:
                        if message["role"] == "assistant":
                            message["content"] = json.dumps({"sentences": [{
                                "text": message["content"], "emotion": "neutral"}]}, ensure_ascii=False)
                    return messages, budget, force_cloud
                client._build_messages = structured_messages
            from config import LOCAL_TEXT_MODEL
            if not client.vision.local_available(LOCAL_TEXT_MODEL):
                raise RuntimeError("Configured local model unavailable")
            client.vision.candidates = lambda **kw: iter([(client.vision.local, LOCAL_TEXT_MODEL)])

            def no_cloud(**kwargs):
                raise RuntimeError("Cloud disabled for this evaluation")
            client.client.chat.completions.create = no_cloud
            if name == "reference":
                client.set_opening("我想给闹钟加个讨价还价的功能。你来定一条规矩？")
            for prompt in prompts:
                metrics = TurnMetrics("continuity-" + args.label)
                sample = {"case": name, "input": prompt}
                try:
                    sample["reply"] = list(client.chat_stream(
                        prompt, metrics=metrics, preview_callback=lambda text: None))
                except Exception as exc:
                    sample["error"] = type(exc).__name__
                sample["timings"] = metrics.values
                output.append(sample)
                print(json.dumps(sample, ensure_ascii=False), flush=True)
                if sample.get("error"):
                    break
        finally:
            client.close()
    path = ROOT / "data" / "logs" / ("continuity-" + args.label + "-" + time.strftime("%Y%m%d-%H%M%S") + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(path), flush=True)


if __name__ == "__main__":
    main()
