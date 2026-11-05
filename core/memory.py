#对话记忆（后期）
# core/memory.py — 对话记忆 + 角色知识库（ChromaDB）
import json
import time
import hashlib
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    import chromadb
    from chromadb.config import Settings
    from chromadb.utils import embedding_functions
    CHROMA_AVAILABLE = True
except ImportError:
    CHROMA_AVAILABLE = False
    print("[Memory] 警告：chromadb 未安装，记忆功能已禁用。")

MEMORY_DIR = Path(__file__).parent.parent / "data" / "memory_db"
EMBED_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"

# 模块级单例，程序启动时预热，避免首次对话卡顿
_ef_singleton = None

def _get_ef():
    global _ef_singleton
    if _ef_singleton is None and CHROMA_AVAILABLE:
        print("[Memory] 预热 embedding 模型...")
        import torch
        torch.set_num_threads(2)
        _ef_singleton = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=EMBED_MODEL, device="cpu"
        )
        print("[Memory] embedding 模型就绪")
    return _ef_singleton


class MemoryManager:
    def __init__(self, persist_dir: Optional[Path] = None):
        self.enabled = CHROMA_AVAILABLE
        if not self.enabled:
            return

        self.persist_dir = persist_dir or MEMORY_DIR
        self.persist_dir.mkdir(parents=True, exist_ok=True)

        self.client = chromadb.PersistentClient(path=str(self.persist_dir),
                                               settings=Settings(anonymized_telemetry=False))
        self.ef = _get_ef()

        self.conv_col = self.client.get_or_create_collection(
            name="conversation_memory",
            embedding_function=self.ef,
            metadata={"hnsw:space": "cosine"},
        )
        self.char_col = self.client.get_or_create_collection(
            name="character_knowledge",
            embedding_function=self.ef,
            metadata={"hnsw:space": "cosine"},
        )

        print(f"[Memory] 已加载记忆库 → {self.persist_dir}")
        print(f"[Memory] 对话记忆：{self.conv_col.count()} 条 | "
              f"角色知识：{self.char_col.count()} 条")

    # ── 对话记忆 ─────────────────────────────

    def save_turn(self, user_text: str, assistant_text: str, emotion: str = "neutral", turn_id=None):
        if not self.enabled:
            return
        ts = int(time.time())
        uid = turn_id or uuid.uuid4().hex
        doc = f"用户：{user_text}\n蕾缪乐：{assistant_text}"
        meta = {"user": user_text, "assistant": assistant_text,
                "emotion": emotion, "timestamp": ts}
        self.conv_col.upsert(documents=[doc], metadatas=[meta], ids=[uid])

    def retrieve_context(self, query: str, n: int = 2) -> str:
        """检索相关历史对话，n 减小到2条加快速度"""
        if not self.enabled or self.conv_col.count() == 0:
            return ""
        n = min(n, self.conv_col.count())
        results = self.conv_col.query(
            query_texts=[query], n_results=n,
            include=["documents", "distances"],
        )
        docs = results["documents"][0]
        distances = results["distances"][0]
        filtered = [doc for doc, dist in zip(docs, distances) if dist < 0.55]
        if not filtered:
            return ""
        lines = ["【相关历史对话】"] + filtered
        return "\n".join(lines)

    # ── 角色知识库 ───────────────────────────

    def retrieve_combined(self, query: str, include_conversations=True, include_character=None, exclude_users=()) -> str:
        """One embedding is reused for both collections by MemoryService."""
        if not self.enabled:
            return ""
        from core.context import character_fact_intent
        if include_character is None:
            include_character = character_fact_intent(query)
        if not include_conversations and not include_character:
            return ""
        vector = self.ef([query])
        sections = []
        for collection, title, limit, cutoff in (
            (self.conv_col, "【旧对话片段：不代表当前状态，与本轮冲突时以本轮为准】", 2, 0.48),
            (self.char_col, "【角色参考】", 2, 0.5),
        ):
            is_conversation = collection is self.conv_col
            if (is_conversation and not include_conversations) or (not is_conversation and not include_character):
                continue
            count = collection.count()
            if not count:
                continue
            options = {"where": {"user": {"$nin": list(exclude_users)}}} if is_conversation and exclude_users else {}
            result = collection.query(query_embeddings=vector, n_results=min(count, limit * 3),
                                      include=["documents", "distances", "metadatas"], **options)
            candidates = []
            seen = set(exclude_users)
            for doc, distance, meta in zip(result["documents"][0], result["distances"][0], result["metadatas"][0]):
                meta = meta or {}
                if distance >= cutoff:
                    continue
                user = meta.get("user", "")
                if is_conversation and (not user or user in seen):
                    continue
                seen.add(user)
                candidates.append((distance, meta.get("timestamp", 0), doc, meta))
            chosen = sorted(candidates, key=lambda item: (item[0], -item[1]))[:limit]
            if is_conversation:
                chosen.sort(key=lambda item: item[1])
            for _, timestamp, doc, meta in chosen:
                if is_conversation:
                    date = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d") if timestamp else "时间未知"
                    doc = (f"时间：{date}\n老板原话：{meta['user']}\n"
                           f"角色当时的回答（不是已确认事实）：{meta.get('assistant', '')}")
                # Keep each excerpt intact; oversize records should not crowd out live dialogue.
                if len(doc) <= 900:
                    sections.append(title + "\n" + doc)
        return "\n\n".join(sections)

    def load_character_data(self, jsonl_path: str, overwrite: bool = False) -> int:
        if not self.enabled:
            return 0
        path = Path(jsonl_path)
        if not path.exists():
            print(f"[Memory] 找不到数据文件：{path}")
            return 0
        if overwrite:
            self.client.delete_collection("character_knowledge")
            self.char_col = self.client.get_or_create_collection(
                name="character_knowledge",
                embedding_function=self.ef,
                metadata={"hnsw:space": "cosine"},
            )
        docs, metas, ids = [], [], []
        count = 0
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                    text = item.get("text", "").strip()
                    if not text:
                        continue
                    uid = hashlib.md5(text.encode()).hexdigest()[:12]
                    docs.append(text)
                    metas.append({"source": item.get("source", "unknown"),
                                  "type": item.get("type", "line")})
                    ids.append(uid)
                    count += 1
                    if len(docs) >= 100:
                        self._batch_add_char(docs, metas, ids)
                        docs, metas, ids = [], [], []
                except json.JSONDecodeError:
                    continue
        if docs:
            self._batch_add_char(docs, metas, ids)
        print(f"[Memory] 已导入角色知识 {count} 条")
        return count

    def _batch_add_char(self, docs, metas, ids):
        try:
            self.char_col.upsert(documents=docs, metadatas=metas, ids=ids)
        except Exception as e:
            print(f"[Memory] 批量写入警告：{e}")

    def retrieve_character_ref(self, query: str, n: int = 2) -> str:
        """检索角色知识，n 保持2条"""
        if not self.enabled or self.char_col.count() == 0:
            return ""
        n = min(n, self.char_col.count())
        results = self.char_col.query(
            query_texts=[query], n_results=n,
            include=["documents", "distances"],
        )
        docs = results["documents"][0]
        distances = results["distances"][0]
        filtered = [doc for doc, dist in zip(docs, distances) if dist < 0.5]
        if not filtered:
            return ""
        lines = ["【角色参考】"] + [f"· {doc}" for doc in filtered]
        return "\n".join(lines)

    # ── 统计 & 清理 ──────────────────────────

    def stats(self) -> dict:
        if not self.enabled:
            return {"enabled": False}
        return {
            "enabled": True,
            "conversation_count": self.conv_col.count(),
            "character_count": self.char_col.count(),
            "persist_dir": str(self.persist_dir),
        }

    def clear_conversations(self):
        if not self.enabled:
            return
        self.client.delete_collection("conversation_memory")
        self.conv_col = self.client.get_or_create_collection(
            name="conversation_memory",
            embedding_function=self.ef,
            metadata={"hnsw:space": "cosine"},
        )
        print("[Memory] 对话记忆已清空")
