"""Local multimodal gateway shared by text, vision and background observations."""
import logging
import json
import os
import threading
import time
import httpx
from openai import OpenAI
from config import (OLLAMA_BASE_URL, LOCAL_TEXT_MODEL, OLLAMA_VISION_MODEL,
                    VISION_MODEL, VISION_BACKEND, REQUEST_TIMEOUT, MODEL, TEXT_BACKEND)
from config import LOCAL_CONTEXT_TOKENS, LOCAL_KEEP_ALIVE, LOCAL_PRESENCE_PENALTY, LOCAL_TOP_P


class VisionBusy(RuntimeError):
    pass


class VisionGateway:
    def __init__(self, cloud):
        self.cloud = cloud
        self.local = OpenAI(api_key="ollama", base_url=OLLAMA_BASE_URL,
                            http_client=httpx.Client(timeout=httpx.Timeout(REQUEST_TIMEOUT, connect=2.0), trust_env=False), max_retries=0)
        self.health = httpx.Client(timeout=1, trust_env=False)
        self.inference = httpx.Client(timeout=httpx.Timeout(REQUEST_TIMEOUT, connect=2), trust_env=False)
        self._lock = threading.Lock()
        self._retry_local_at = {}
        self._health_until = 0.0
        self._healthy = False
        self._closed = threading.Event()
        self.foreground_requested = threading.Event()
        if (VISION_BACKEND != "cloud" or TEXT_BACKEND != "cloud") and os.getenv("LOCAL_VISION_WARMUP", "1") == "1":
            threading.Thread(target=self._warmup, daemon=True).start()

    def _warmup(self):
        # Text conversation is the common path. Loading both models on an 8 GB GPU
        # would cause immediate eviction and make startup slower rather than faster.
        model = LOCAL_TEXT_MODEL if TEXT_BACKEND != "cloud" else OLLAMA_VISION_MODEL
        if not self.local_available(model) or self._closed.is_set():
            return
        try:
            self.acquire(background=True)
        except VisionBusy:
            return
        try:
            url = OLLAMA_BASE_URL.rstrip("/").removesuffix("/v1") + "/api/generate"
            response = self.inference.post(url, json={"model": model, "prompt": "", "stream": False,
                                             "keep_alive": LOCAL_KEEP_ALIVE, "think": False,
                                             "options": {"num_ctx": LOCAL_CONTEXT_TOKENS}})
            response.raise_for_status()
            logging.info("Local model preloaded: %s", model)
        except Exception as exc:
            logging.warning("Vision warmup skipped: %s", type(exc).__name__)
        finally:
            self.release()

    def local_available(self, model=None):
        model = model or OLLAMA_VISION_MODEL
        if time.monotonic() < max(self._retry_local_at.get("*", 0), self._retry_local_at.get(model, 0)):
            return False
        now = time.monotonic()
        if now < self._health_until:
            return model in getattr(self, "_available_models", set())
        try:
            url = OLLAMA_BASE_URL.rstrip("/").removesuffix("/v1") + "/api/tags"
            result = self.health.get(url)
            result.raise_for_status()
            names = [item.get("name", "") for item in result.json().get("models", [])]
            self._available_models = set(names)
            self._healthy = model in self._available_models
        except Exception:
            self._available_models = set()
            self._healthy = False
        self._health_until = now + 15
        return model in getattr(self, "_available_models", set())

    def candidates(self, text=False):
        local_model = LOCAL_TEXT_MODEL if text else OLLAMA_VISION_MODEL
        backend = TEXT_BACKEND if text else VISION_BACKEND
        if backend != "cloud" and self.local_available(local_model):
            yield self.local, local_model
        yield self.cloud, MODEL if text else VISION_MODEL

    def failed(self, client, model=None):
        if client is self.local:
            self._retry_local_at[model or "*"] = time.monotonic() + 30
            logging.warning("Local model %s failed; cloud fallback, retry in 30s", model or "unknown")

    @staticmethod
    def native_messages(messages):
        output = []
        for message in messages:
            content = message["content"]
            item = {"role": message["role"], "content": content}
            if isinstance(content, list):
                item["content"] = "\n".join(part.get("text", "") for part in content if part.get("type") == "text")
                images = []
                for part in content:
                    if part.get("type") == "image_url":
                        url = part["image_url"]["url"]
                        if not url.startswith("data:image/") or ";base64," not in url:
                            raise ValueError("Local vision requires an inline base64 image")
                        images.append(url.split(";base64,", 1)[1])
                if images:
                    item["images"] = images
            output.append(item)
        return output

    def stream_local(self, messages, model=OLLAMA_VISION_MODEL, max_tokens=450, temperature=0.75, metrics=None, output_format=None):
        """Native API applies context/residency on every request and exposes actual timings."""
        url = OLLAMA_BASE_URL.rstrip("/").removesuffix("/v1") + "/api/chat"
        payload = {"model": model, "messages": self.native_messages(messages), "stream": True,
                   "think": False, "keep_alive": LOCAL_KEEP_ALIVE,
                   "options": {"num_ctx": LOCAL_CONTEXT_TOKENS, "num_predict": max_tokens,
                               "temperature": temperature, "top_p": LOCAL_TOP_P, "presence_penalty": LOCAL_PRESENCE_PENALTY,
                               "repeat_penalty": 1.0}}
        if output_format:
            payload["format"] = output_format
        with self.inference.stream("POST", url, json=payload) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line:
                    continue
                event = json.loads(line)
                if event.get("error"):
                    raise RuntimeError("Ollama generation failed")
                if event.get("done") and metrics is not None:
                    for key in ("load_duration", "prompt_eval_duration", "eval_duration"):
                        if key in event:
                            metrics.values["local_" + key + "_ms"] = round(event[key] / 1_000_000, 1)
                    for key in ("prompt_eval_count", "prompt_eval_cached_count", "eval_count"):
                        if key in event:
                            metrics.values["local_" + key] = event[key]
                text = event.get("message", {}).get("content", "")
                if text:
                    yield text

    def acquire(self, background=False, timeout=None):
        if background and self.foreground_requested.is_set():
            raise VisionBusy("Foreground conversation has priority")
        acquired = self._lock.acquire(False) if background else self._lock.acquire(timeout=REQUEST_TIMEOUT if timeout is None else timeout)
        if not acquired:
            raise VisionBusy("Vision is occupied")

    def release(self):
        self._lock.release()

    def complete(self, messages, background=False, max_tokens=300):
        if background and TEXT_BACKEND != "cloud" and VISION_BACKEND != "cloud" and LOCAL_TEXT_MODEL != OLLAMA_VISION_MODEL:
            # Ambient vision must not evict the resident chat model on an 8 GB GPU.
            raise VisionBusy("Background vision paused while local text and vision models differ")
        self.acquire(background)
        try:
            for client, model in self.candidates():
                try:
                    if client is self.local:
                        chunks = self.stream_local(messages, model=model, max_tokens=max_tokens, temperature=0.3)
                        try:
                            raw = ""
                            for text in chunks:
                                if self._closed.is_set() or (background and self.foreground_requested.is_set()):
                                    raise VisionBusy("Background vision yielded to user")
                                raw += text
                            if not raw:
                                raise ValueError("Empty vision result")
                            return raw
                        finally:
                            if hasattr(chunks, "close"):
                                chunks.close()
                    kwargs = dict(model=model, messages=messages, temperature=0.3, max_tokens=max_tokens,
                                  extra_body={"reasoning_effort": "none"} if client is self.local and "qwen3" in model.lower() else {})
                    if background:
                        chunks = client.chat.completions.create(**kwargs, stream=True)
                        try:
                            raw = ""
                            for chunk in chunks:
                                if self.foreground_requested.is_set() or self._closed.is_set():
                                    raise VisionBusy("Background vision yielded to user")
                                if chunk.choices:
                                    raw += chunk.choices[0].delta.content or ""
                            return raw
                        finally:
                            if hasattr(chunks, "close"):
                                chunks.close()
                    response = client.chat.completions.create(**kwargs)
                    if not response or not response.choices or not response.choices[0].message.content:
                        raise ValueError("Empty vision result")
                    return response.choices[0].message.content
                except VisionBusy:
                    raise
                except Exception:
                    self.failed(client, model)
                    if client is self.cloud:
                        raise
            return ""
        finally:
            self.release()

    def close(self):
        self._closed.set()
        self.health.close()
        self.inference.close()
        self.local.close()
