#!/usr/bin/env python
# data/collect_character_data.py — 角色数据收集与清洗工具
"""
用途：
  1. 从手动整理的原始文本（txt）批量转换为 memory.py 需要的 JSONL 格式
  2. 提供交互式"逐条添加台词"工具
  3. 提供数据统计与预览

使用方式：
  python data/collect_character_data.py --mode convert --input raw_lines.txt
  python data/collect_character_data.py --mode add
  python data/collect_character_data.py --mode stats
  python data/collect_character_data.py --mode load   （将 JSONL 导入 ChromaDB）

JSONL 输出路径：data/character/lines.jsonl
"""

import json
import argparse
import sys
from pathlib import Path

# ── 路径配置 ──────────────────────────────────────────────────────
BASE_DIR  = Path(__file__).parent.parent          # 项目根目录
DATA_DIR  = BASE_DIR / "data" / "character"
JSONL_OUT = DATA_DIR / "lines.jsonl"

# 数据类型说明
TYPE_LABELS = {
    "line":        "游戏台词（战斗/交互语音）",
    "lore":        "角色背景/剧情文本",
    "story":       "活动/主线剧情对话",
    "preference":  "角色喜好/性格描述",
    "custom":      "自定义补充",
}


# ── 工具函数 ──────────────────────────────────────────────────────

def ensure_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_existing() -> list[dict]:
    if not JSONL_OUT.exists():
        return []
    items = []
    with open(JSONL_OUT, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    items.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return items


def save_all(items: list[dict]):
    ensure_dir()
    with open(JSONL_OUT, "w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(f"[收集器] 已保存 {len(items)} 条 → {JSONL_OUT}")


def append_item(item: dict):
    ensure_dir()
    with open(JSONL_OUT, "a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")


# ── 模式：从 TXT 批量转换 ─────────────────────────────────────────

def mode_convert(input_path: str, source: str, dtype: str):
    """
    TXT 文件格式：每行一条台词，空行跳过，# 开头的行为注释。
    
    示例 raw_lines.txt：
        # 战斗语音
        嗯…上！
        没问题，包在蕾缪乐身上！
        # 信任提升
        博士今天也很努力呢～
    """
    path = Path(input_path)
    if not path.exists():
        print(f"[收集器] 找不到文件：{path}")
        sys.exit(1)

    items = []
    with open(path, encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            items.append({
                "text": line,
                "source": source,
                "type": dtype,
            })

    if not items:
        print("[收集器] 未读到有效数据")
        return

    # 去重（与已有数据合并）
    existing = load_existing()
    existing_texts = {i["text"] for i in existing}
    new_items = [i for i in items if i["text"] not in existing_texts]

    if not new_items:
        print("[收集器] 所有条目均已存在，无需添加")
        return

    for item in new_items:
        append_item(item)

    print(f"[收集器] 转换完成：新增 {len(new_items)} 条，跳过重复 {len(items)-len(new_items)} 条")
    print(f"[收集器] 输出文件：{JSONL_OUT}")


# ── 模式：交互式逐条添加 ──────────────────────────────────────────

def mode_add():
    """
    交互式命令行，逐条输入台词并选择类型。
    输入空行结束。
    """
    print("\n=== 蕾缪乐角色数据收集器（交互模式）===")
    print("每次输入一条台词/文本，回车确认。空行结束。\n")

    print("数据类型：")
    for k, v in TYPE_LABELS.items():
        print(f"  {k:12s} → {v}")
    print()

    dtype = input("选择类型（默认 line）：").strip() or "line"
    if dtype not in TYPE_LABELS:
        print(f"[警告] 未知类型 '{dtype}'，使用 'custom'")
        dtype = "custom"

    source = input("来源标注（如：信任语音/主线第三章，默认 manual）：").strip() or "manual"

    count = 0
    print("\n开始输入（空行结束）：")
    while True:
        try:
            text = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text:
            break
        append_item({"text": text, "source": source, "type": dtype})
        count += 1
        print(f"  ✓ 已添加 [{count}]")

    print(f"\n[收集器] 本次新增 {count} 条，保存至 {JSONL_OUT}")


# ── 模式：统计预览 ────────────────────────────────────────────────

def mode_stats():
    items = load_existing()
    if not items:
        print(f"[收集器] 暂无数据（{JSONL_OUT}）")
        return

    from collections import Counter
    type_count = Counter(i.get("type", "unknown") for i in items)
    source_count = Counter(i.get("source", "unknown") for i in items)

    print(f"\n=== 数据统计 ({JSONL_OUT}) ===")
    print(f"总计：{len(items)} 条\n")

    print("按类型：")
    for t, c in type_count.most_common():
        label = TYPE_LABELS.get(t, t)
        print(f"  {t:12s} {c:4d} 条  （{label}）")

    print("\n按来源（Top 10）：")
    for s, c in source_count.most_common(10):
        print(f"  {s:20s} {c:4d} 条")

    print("\n前 5 条预览：")
    for item in items[:5]:
        text_preview = item["text"][:40] + ("…" if len(item["text"]) > 40 else "")
        print(f"  [{item.get('type','?')}] {text_preview}")


# ── 模式：导入 ChromaDB ───────────────────────────────────────────

def mode_load(overwrite: bool = False):
    """将 JSONL 文件导入 ChromaDB 记忆库。"""
    if not JSONL_OUT.exists():
        print(f"[收集器] 找不到数据文件：{JSONL_OUT}")
        print("请先用 --mode convert 或 --mode add 收集数据")
        sys.exit(1)

    # 将项目根加入 path
    sys.path.insert(0, str(BASE_DIR))

    try:
        from core.memory import MemoryManager
    except ImportError as e:
        print(f"[收集器] 无法导入 MemoryManager：{e}")
        sys.exit(1)

    mem = MemoryManager()
    count = mem.load_character_data(str(JSONL_OUT), overwrite=overwrite)
    stats = mem.stats()
    print(f"\n[收集器] 导入完成！当前知识库：{stats['character_count']} 条")


# ── 内置示例数据生成 ──────────────────────────────────────────────

def mode_demo():
    """
    生成一批示例数据（明日方舟蕾缪乐风格），
    用于在没有真实数据时测试记忆检索功能。
    """
    demo_items = [
        # 战斗/互动语音风格
        {"text": "蕾缪乐，出击！", "source": "战斗语音", "type": "line"},
        {"text": "没问题的，交给蕾缪乐吧～", "source": "战斗语音", "type": "line"},
        {"text": "嗯……感觉还不错！", "source": "战斗语音", "type": "line"},
        {"text": "博士，要一起去看看吗？", "source": "互动语音", "type": "line"},
        {"text": "今天的任务完成啦！", "source": "战斗语音", "type": "line"},
        {"text": "蕾缪乐会好好保护大家的！", "source": "战斗语音", "type": "line"},
        # 信任/性格
        {"text": "博士，你今天也辛苦了呢。有什么想说的就说吧，蕾缪乐一直在这里。",
         "source": "信任语音", "type": "line"},
        {"text": "我虽然有点迷糊，但做事情还是很认真的哦！",
         "source": "自我介绍", "type": "line"},
        {"text": "哎呀，蕾缪乐有时候会想太多……不过没关系，一步一步来就好！",
         "source": "信任语音", "type": "line"},
        # 性格描述
        {"text": "蕾缪乐是一个活泼开朗的角色，偶尔会有点小迷糊，但对朋友非常温柔。",
         "source": "角色设定", "type": "preference"},
        {"text": "蕾缪乐喜欢甜食，尤其是草莓味的东西，看到美食就会眼睛发光。",
         "source": "角色设定", "type": "preference"},
        {"text": "蕾缪乐说话时习惯在句尾加上轻松的语气词，让人感觉很亲近。",
         "source": "角色设定", "type": "preference"},
        {"text": "面对困难时，蕾缪乐不会轻易放弃，会用乐观的态度面对挑战。",
         "source": "角色设定", "type": "preference"},
        # 背景/剧情
        {"text": "作为罗德岛的干员，蕾缪乐认为守护大家是最重要的事情。",
         "source": "背景设定", "type": "lore"},
        {"text": "蕾缪乐在战斗中展现出与平时不同的专注与力量，让队友十分放心。",
         "source": "背景设定", "type": "lore"},
    ]

    ensure_dir()
    existing = load_existing()
    existing_texts = {i["text"] for i in existing}
    new_items = [i for i in demo_items if i["text"] not in existing_texts]

    for item in new_items:
        append_item(item)

    print(f"[收集器] 示例数据已生成：新增 {len(new_items)} 条 → {JSONL_OUT}")


# ── 入口 ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="蕾缪乐角色数据收集工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python data/collect_character_data.py --mode demo          # 生成示例数据
  python data/collect_character_data.py --mode stats         # 查看统计
  python data/collect_character_data.py --mode add           # 交互式添加
  python data/collect_character_data.py --mode convert \\
      --input raw.txt --source 战斗语音 --type line          # 批量导入TXT
  python data/collect_character_data.py --mode load          # 导入ChromaDB
  python data/collect_character_data.py --mode load --overwrite  # 覆盖导入
        """,
    )
    parser.add_argument("--mode", choices=["convert", "add", "stats", "load", "demo"],
                        default="stats", help="运行模式")
    parser.add_argument("--input",  default="",      help="TXT 输入文件路径（convert 模式）")
    parser.add_argument("--source", default="manual", help="来源标注")
    parser.add_argument("--type",   default="line",
                        choices=list(TYPE_LABELS.keys()), help="数据类型")
    parser.add_argument("--overwrite", action="store_true",
                        help="load 模式：覆盖现有知识库")

    args = parser.parse_args()

    if args.mode == "convert":
        if not args.input:
            print("[收集器] convert 模式需要 --input 参数")
            sys.exit(1)
        mode_convert(args.input, args.source, args.type)
    elif args.mode == "add":
        mode_add()
    elif args.mode == "stats":
        mode_stats()
    elif args.mode == "load":
        mode_load(overwrite=args.overwrite)
    elif args.mode == "demo":
        mode_demo()


if __name__ == "__main__":
    main()
