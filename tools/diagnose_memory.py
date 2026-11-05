"""Read-only retrieval timing against the existing local memory database."""
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")
start = time.perf_counter()
from core.memory import MemoryManager
manager = MemoryManager()
result = {"startup_ms": round((time.perf_counter() - start) * 1000), "stats": manager.stats(), "queries": []}
for _ in range(3):
    started = time.perf_counter()
    found = manager.retrieve_combined("姐姐蕾缪安")
    result["queries"].append({"ms": round((time.perf_counter() - started) * 1000), "result_chars": len(found)})
started = time.perf_counter()
found = manager.retrieve_combined("上次说的安排", include_character=False,
                                  exclude_users=("synthetic diagnostic exclusion",))
result["archive_filter"] = {"ms": round((time.perf_counter() - started) * 1000), "result_chars": len(found)}
print(json.dumps(result, ensure_ascii=False), flush=True)
