"""Ordered dialogue selection and retrieval policy, without inference or embeddings."""
from dataclasses import dataclass
import re

from core.context import character_fact_intent, estimate_tokens


CONTINUITY_PROMPT = """【接续对话】
按时间理解最近的对话，先确定当前说的是谁、哪件事，以及老板在回应你的哪句话，再作答。
“他／它／那个／第二个／为什么”优先指向最近对话的对象；明确时直接接话，不清楚才问一句。
老板的新纠正、改口和决定优先于旧说法；保留未被修改的条件。你提过的建议不等于老板已经同意。
你之前的回答也可能出错，不能把自己的无依据说法延续成事实。别替第三者断言动机或作心理诊断。
不要只重复关键词：回应这句话在上文中的意思，区分事实、猜测、假设和情绪；两种情绪可以同时存在。
老板明确换话题就跟随，不强拉回旧话题。可以沿用相关名字与细节，不用每次复述整个背景。
历史检索片段可能不属于同一件事，不能据此改写当前事实，也不能把你以前的推测当成老板说过的话。"""


def dialogue_units(history):
    """A user turn includes all following assistant utterances until the next user."""
    units = []
    for message in history:
        if message["role"] == "user" or not units:
            units.append([])
        units[-1].append(message)
    return units


def message_cost(messages):
    return sum(estimate_tokens(message["content"]) + 6 for message in messages)


def recent_cost(history, turns=4):
    return message_cost([message for unit in dialogue_units(history)[-turns:] for message in unit])


def prepare_prompt_history(history, current_text):
    """A non-destructive request view: isolate unrelated play and unreliable replies.

    This is a narrow heuristic for observed failure patterns, not a fact checker.
    Original records and user corrections stay intact on disk and in session memory.
    """
    papers = re.compile(r"论文|文献|公式|推导|摘要")
    units = dialogue_units(history)
    task = bool(papers.search(current_text)) and not re.search(r"不(?:看|聊|讨论)|聊.{0,6}(?:感觉|心情)", current_text)
    if task:
        start = next((i for i, unit in enumerate(units)
                      if any(m["role"] == "user" and papers.search(m["content"]) for m in unit)), len(units))
        units = units[start:]
    output = []
    has_material = False
    for unit in units:
        user = "\n".join(m["content"] for m in unit if m["role"] == "user")
        has_material |= bool(re.search(r"\[图像\]|(?:原文|摘要|公式|代码)[：:]|```", user))
        imaginative = bool(re.search(r"编.{0,4}故事|开玩笑|用.{0,12}比喻|假设|假如", user))
        for message in unit:
            content = message["content"]
            if message["role"] == "assistant":
                mixed_metaphor = (re.search(r"论文|公式|新内容|旧内容", content)
                                  and re.search(r"苹果派|香味|闹钟|礼物盒|零件", content)
                                  and re.search(r"拆|闻|吃|藏", content))
                unsupported_summary = (task and not has_material
                                       and re.search(r"(?:第.{1,3}篇(?:论文)?|这篇论文).{0,8}(?:讲|研究|讨论|提出)", content))
                if (mixed_metaphor and not imaginative) or unsupported_summary:
                    output.append({"role": "assistant", "content": "[该条旧回复已隔离，没有可用于本轮作答的可靠信息。]"})
                    continue
            output.append(dict(message))
    return output


def material_state_note(history, current_text, has_image=False):
    if not re.search(r"论文|文献|摘要|第一篇", current_text):
        return ""
    users = [m["content"] for m in history if m["role"] == "user"] + [current_text]
    supplied = has_image or any(re.search(r"\[图像\]|(?:原文|摘要|正文)[：:]|```", text)
                               or len(text) > 300 for text in users)
    if supplied:
        return ""
    return ("【材料状态】能力：可以阅读并解释用户贴出的论文文字和本轮截图。当前收到的只有对话问题，没有可核验的论文正文或截图。"
            "下一步是请用户贴出摘要/段落或明确要求看屏幕；现在尚不能判断任何一篇论文的内容，旧回复里的主题也未经核验。")


def select_dialogue(history, budget):
    """Keep a contiguous recent transcript and, when needed, older verbatim excerpts.

    Excerpts retain speaker and order. They are not generated summaries or inferred facts.
    Older corrections/decisions are preferred, but never displace the latest four turns.
    """
    units = dialogue_units(history)
    if message_cost(history) <= budget:
        return list(history), ""
    note_budget = min(400, max(0, budget - recent_cost(history)), max(0, budget // 5))
    kept = []
    used = 0
    for unit in reversed(units):
        cost = message_cost(unit)
        if used + cost > budget - note_budget:
            break
        kept.insert(0, unit)
        used += cost
    dropped = units[:len(units) - len(kept)]
    heading = "【更早对话原文节选：有省略，按先后排列；与后文冲突以后文为准】\n"
    important = re.compile(r"更正|不是|改为|改成|改主意|决定|约好|记住|以后|不要|别.{0,4}(?:再|叫|提)|我叫|我喜欢")
    ranked = sorted(enumerate(dropped), key=lambda pair: (
        any(important.search(m["content"]) for m in pair[1] if m["role"] == "user"), pair[0]), reverse=True)
    selected = []
    for index, unit in ranked:
        excerpt = "\n".join(("老板：" if m["role"] == "user" else "你：") + m["content"] for m in unit)
        candidate = sorted(selected + [(index, excerpt)])
        note = heading + "\n\n".join(value for _, value in candidate)
        if estimate_tokens(note) <= note_budget:
            selected = candidate
    note = heading + "\n\n".join(value for _, value in sorted(selected)) if selected else ""
    # Unused excerpt space belongs to the contiguous transcript.
    while dropped:
        unit = dropped[-1]
        if used + message_cost(unit) + (estimate_tokens(note) if note else 0) > budget:
            break
        index = len(dropped) - 1
        dropped.pop()
        kept.insert(0, unit)
        used += message_cost(unit)
        selected = [(i, value) for i, value in selected if i != index]
        note = heading + "\n\n".join(value for _, value in sorted(selected)) if selected else ""
    return [message for unit in kept for message in unit], note


@dataclass(frozen=True)
class RetrievalPlan:
    query: str
    conversations: bool
    character: bool
    exclude_users: tuple

    def options(self):
        return {"include_conversations": self.conversations, "include_character": self.character,
                "exclude_users": self.exclude_users}


def retrieval_plan(text, history):
    # Ordinary follow-ups need the transcript, not keyword-similar archived conversations.
    recall = bool(re.search(r"记得|记不记得|上次|以前.{0,6}(?:说|聊|提)|之前.{0,6}(?:说|聊|提)|曾经|还记着", text))
    if re.search(r"(?:不|别|不要|不用).{0,3}(?:提|回忆|翻).{0,3}(?:上次|过去|以前|旧)|不聊.{0,3}(?:上次|以前)", text):
        recall = False
    character = character_fact_intent(text)
    if not recall and not character:
        return None
    users = tuple(re.sub(r"^\[此前对话 [^\]]+\] ", "", m["content"])
                  for m in history if m["role"] == "user")
    query = text
    if recall and len(text) < 28 and re.search(r"那|这|它|他|她|之前|上次", text):
        query = "\n".join((*users[-2:], text))[-500:]
    return RetrievalPlan(query, recall, character, users)


def bounded_reference(text, budget):
    """Use whole reference paragraphs; never cut a correction or negation mid-sentence."""
    parts = []
    for paragraph in text.split("\n\n"):
        candidate = "\n\n".join(parts + [paragraph])
        if estimate_tokens(candidate) <= budget:
            parts.append(paragraph)
    return "\n\n".join(parts)


def user_constraints(history, current_text, budget=220):
    """Pin recent explicit user conditions verbatim, never the assistant's guesses."""
    topic_change = re.compile(r"换个话题|换一个话题|不聊.{0,8}了|先不说.{0,8}了")
    if topic_change.search(current_text):
        return ""
    condition = re.compile(r"最多|至少|只能|只给|必须|不要|不用|不是|改成|改为|改主意|更正|约好|决定|我介意|我烦的是")
    statements = []
    for message in history[-16:]:
        if message["role"] != "user":
            continue
        text = message["content"]
        if topic_change.search(text):
            statements.clear()
        if condition.search(text):
            statements.append(text)
    heading = "【用户明确说过的条件，原话按先后排列；后来的改口只覆盖相应部分，当前输入优先】\n"
    selected = []
    for text in reversed(statements):
        candidate = heading + "\n".join([text, *selected])
        if estimate_tokens(candidate) <= budget:
            selected.insert(0, text)
    return heading + "\n".join(selected) if selected else ""
