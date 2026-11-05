"""Local-only synthetic conversations; compare content and visible-text latency."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CASES = {
    "grounded_discussion": [
        "我在读一篇论文，有个公式没看懂。你能帮我理解吗？",
        "论文和公式我还没发给你，你现在能看懂哪些内容？",
        "先不看论文了。做题总卡在同一步让我挺烦的，你别急着给建议，就聊聊这种感觉。",
    ],
    "mixed_feelings": [
        "朋友约我周末见面，后来取消了。我明明有点失落，又觉得终于能歇着了。",
        "不是怕他不在乎我。我只是最近太累，但又真的想见他，别把这个说成关系危机。",
        "你自己怎么看这种两头都想要的感觉？可以多说一点，别只把我的话换个说法。",
    ],
    "own_opinion": [
        "随便聊聊，你有没有什么想认真琢磨的小点子？不用问我选什么话题。",
        "先别换话题，你觉得这个点子最有意思的地方是什么？也说说哪里可能行不通。",
        "别顺着我说好听的，你会留下什么，又会舍掉什么？说说理由。",
    ],
    "length_control": [
        "我练吉他一周了，同一小节弹错二十遍，感觉自己没什么天分。别给训练清单，我想聊聊这件事。",
        "我不是急着变厉害，是害怕努力了也没用。这个区别对你来说重要吗？展开说说。",
        "嗯，这次只用一句话接我就好。",
    ],
    "fresh_followup": [
        "我发现自己看电影时老是猜结局，猜对了又觉得没惊喜，挺扫兴的。你怎么看？",
        "我不是想找一部反转更多的片子，是不知道怎么享受已经猜到的故事。",
        "那你会更在意结局出乎意料，还是中间的人物让你相信？讲讲你的取舍。",
    ],
}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--case", choices=CASES)
    parser.add_argument("--thinking", action="store_true", help="Diagnostic only; does not change app configuration")
    parser.add_argument("--plain-json", action="store_true", help="Compare JSON mode against schema-constrained generation")
    parser.add_argument("--temperature", type=float)
    parser.add_argument("--top-p", type=float)
    parser.add_argument("--style-demo", action="store_true", help="Test an isolated, non-canonical writing example")
    args = parser.parse_args()
    os.environ["LOCAL_VISION_WARMUP"] = "0"
    os.environ["TEXT_BACKEND"] = "auto"
    from config import LOCAL_TEXT_MODEL
    from core.llm import LLMClient
    from core.metrics import TurnMetrics
    if args.style_demo:
        import core.llm as conversation
        conversation.CHARACTER_PROMPT += """
【写法示范，不是角色资料，不是你或老板的经历，不得当作记忆引用】
假设有人说：我想把爱好当工作，又怕最后连它也不喜欢了。
一种回应：这个担心我倒觉得有道理。喜欢一样东西，和每天必须交出成果，不是一回事。不过我也不想替你把那条路堵死：你向往的是能一直做喜欢的事，还是终于能自己安排日子？这两种愿望，未必非得打包实现。
只学习怎样从具体问题展开自己的理由和取舍，不复制内容、问法或句式。
"""

    samples = []
    client = LLMClient(use_memory=False)
    try:
        if not client.vision.local_available(LOCAL_TEXT_MODEL):
            raise RuntimeError("Configured local model unavailable")
        client.vision.candidates = lambda **kw: [(client.vision.local, LOCAL_TEXT_MODEL)]

        def no_cloud(**kwargs):
            raise RuntimeError("Cloud disabled for this evaluation")

        client.client.chat.completions.create = no_cloud
        native_stream = client.vision.inference.stream

        def diagnostic_stream(*positional, **kwargs):
            payload = kwargs.get("json", {})
            if args.thinking:
                payload["think"] = True
            if args.plain_json:
                payload["format"] = "json"
            if args.temperature is not None:
                payload["options"]["temperature"] = args.temperature
            if args.top_p is not None:
                payload["options"]["top_p"] = args.top_p
            return native_stream(*positional, **kwargs)

        client.vision.inference.stream = diagnostic_stream
        for name, prompts in CASES.items():
            if args.case and args.case != name:
                continue
            client.clear_history()
            for prompt in prompts:
                metrics = TurnMetrics("naturalness-" + args.label)
                sample = {"case": name, "input": prompt}
                try:
                    sample["reply"] = list(client.chat_stream(
                        prompt, metrics=metrics, preview_callback=lambda text: None))
                    sample["characters"] = sum(len(s["text"]) for s in sample["reply"])
                except Exception as exc:
                    sample["error"] = type(exc).__name__ + ": " + str(exc)
                sample["timings"] = metrics.values
                samples.append(sample)
                print(json.dumps(sample, ensure_ascii=False), flush=True)
                if "error" in sample:
                    break
    finally:
        client.close()
    path = ROOT / "data" / "logs" / ("naturalness-" + args.label + "-" + time.strftime("%Y%m%d-%H%M%S") + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(samples, ensure_ascii=False, indent=2), encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()
