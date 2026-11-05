"""Conversation orchestration: transport, parsing, memory and input context stay separate."""
import threading
from openai import OpenAI
from config import (DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, MODEL, TEXT_BACKEND,
                    CHARACTER_PROMPT, ACTION_PROMPT, REQUEST_TIMEOUT, MEMORY_WAIT_SECONDS, LOCAL_CONTEXT_TOKENS, VISION_MODEL, CHAT_TEMPERATURE)
from core.context import Interaction, ObservationStore, reply_style, action_intent, memory_budget, estimate_tokens, grounding_guidance
from core.conversation import (CONTINUITY_PROMPT, retrieval_plan, select_dialogue,
                               recent_cost, message_cost, bounded_reference, user_constraints)
from core.conversation import prepare_prompt_history, material_state_note
from core.protocol import SentenceParser, parse_response, extract_object, SENTENCE_SCHEMA
from core.metrics import TurnMetrics
from core.vision import VisionGateway, VisionBusy
from core.transport import cloud_http_client
from core.character import get_character_guide


class LLMClient:
    def __init__(self, use_memory=True):
        self.client = OpenAI(api_key=DEEPSEEK_API_KEY or "not-configured", base_url=DEEPSEEK_BASE_URL,
                             http_client=cloud_http_client(REQUEST_TIMEOUT), max_retries=0)
        self.vision = VisionGateway(self.client)
        self.observations = ObservationStore()
        self.history = []
        self._history_lock = threading.Lock()
        self._closed = False
        self.memory_service = None
        self.session_state = None
        self._opening = ""
        if use_memory:
            from core.social import get_session_state
            self.session_state = get_session_state()
            self.history = self.session_state.recent_history()
            from core.memory_service import MemoryService
            self.memory_service = MemoryService()

    @property
    def memory(self):
        return self.memory_service.manager if self.memory_service else None

    def _build_messages(self, interaction, metrics):
        style, tokens = reply_style(interaction.text)
        original_history = self._sanitized_history()
        history = prepare_prompt_history(original_history, interaction.text)
        material_note = material_state_note(original_history, interaction.text, bool(interaction.screen_b64 or interaction.camera_b64))
        metrics.values["history_entries_isolated"] = len(original_history) - len(history) + sum(
            m["content"].startswith("[该条旧回复已隔离") for m in history)
        guide = get_character_guide()
        # Stable leading instructions preserve the local model's reusable prompt prefix.
        system = guide.identity() + "\n" + CHARACTER_PROMPT + "\n" + CONTINUITY_PROMPT
        policy = "\n\n".join(filter(None, [style, grounding_guidance(interaction.text),
            material_note,
            ACTION_PROMPT if action_intent(interaction.text) else "",
            guide.context(interaction.text)]))
        system += "\n【本轮表达要求】\n" + policy
        content = interaction.content()
        image_tokens = 750 * (bool(interaction.screen_b64) + bool(interaction.camera_b64))
        remaining = LOCAL_CONTEXT_TOKENS - estimate_tokens(system) - estimate_tokens(interaction.text + interaction.notes) - image_tokens - tokens - 256
        # Reserve recent complete turns before allocating any space to optional references.
        reference_budget = min(450, max(0, remaining - recent_cost(history)))
        constraints = user_constraints(original_history, interaction.text, min(220, reference_budget))
        reference_budget -= estimate_tokens(constraints) if constraints else 0
        plan = retrieval_plan(interaction.text, history)
        context = ""
        if plan and self.memory_service and reference_budget >= 100:
            context = self.memory_service.retrieve(plan.query, memory_budget(interaction.text, MEMORY_WAIT_SECONDS), **plan.options())
        metrics.mark("memory_ready")
        metrics.values["memory_requested"] = bool(plan and self.memory_service and reference_budget >= 100)
        optional_context = bounded_reference("\n\n".join(filter(None, [
            "" if material_note else getattr(self, "_opening", ""),
            self.observations.context(), context])), reference_budget)
        turn_context = "\n\n".join(filter(None, [constraints, optional_context]))
        remaining -= estimate_tokens(turn_context) if turn_context else 0
        force_cloud = remaining < recent_cost(history, turns=1)
        selected, earlier = select_dialogue(history, max(0, remaining)) if not force_cloud else (history, "")
        reference_text = "\n\n".join(filter(None, [earlier, turn_context]))
        reference = ("【补充参考，非当前输入】\n" + reference_text + "\n【当前输入】\n") if reference_text else ""
        if isinstance(content, str):
            content = reference + content
        else:
            content = [{"type": "text", "text": reference}, *content]
        metrics.values["history_turns_available"] = sum(m["role"] == "user" for m in history)
        metrics.values["history_turns_sent"] = sum(m["role"] == "user" for m in selected)
        metrics.values["earlier_excerpt_tokens"] = estimate_tokens(earlier) if earlier else 0
        metrics.values["memory_reference_tokens"] = estimate_tokens(turn_context) if turn_context else 0
        metrics.values["prompt_estimated_tokens"] = estimate_tokens(system + reference + interaction.text + interaction.notes) + message_cost(selected) + image_tokens
        return [{"role": "system", "content": system}, *selected,
                {"role": "user", "content": content}], tokens, force_cloud

    def prefetch_memory(self, text):
        plan = retrieval_plan(text, self._sanitized_history())
        if plan and self.memory_service:
            self.memory_service.prefetch(plan.query, **plan.options())

    def chat_stream(self, user_input, screen_b64="", camera_b64="", source="text", notes="",
                    stop_event=None, metrics=None, preview_callback=None, record_turn=True):
        interaction = Interaction(user_input, source, screen_b64, camera_b64, notes)
        metrics = metrics or TurnMetrics(source)
        sentences = []
        status = "error"
        has_image = bool(screen_b64 or camera_b64)
        gateway = getattr(self, "vision", None)
        routed = has_image or (TEXT_BACKEND != "cloud" and gateway is not None)
        acquired = False
        try:
            messages, token_limit, force_cloud = self._build_messages(interaction, metrics)
            if force_cloud:
                candidates = [(self.client, VISION_MODEL if has_image else MODEL)]
            elif routed:
                gateway.foreground_requested.set()
                try:
                    # Background SSE observes this event and releases the shared local model.
                    gateway.acquire(timeout=3)
                    acquired = True
                    candidates = self.vision.candidates(text=not has_image)
                except VisionBusy:
                    # A background observation must never make a user wait for the GPU.
                    candidates = [(self.client, VISION_MODEL if has_image else MODEL)]
            else:
                candidates = [(self.client, MODEL)]
            for client, model in candidates:
                parser = SentenceParser()
                response = None
                try:
                    metrics.model = model
                    kwargs = dict(model=model, messages=messages, temperature=CHAT_TEMPERATURE,
                                  max_tokens=token_limit, stream=True)
                    if model == "Pro/deepseek-ai/DeepSeek-V3.2":
                        kwargs["extra_body"] = {"enable_thinking": False}
                    elif acquired and client is self.vision.local and "qwen3" in model.lower():
                        kwargs["extra_body"] = {"reasoning_effort": "none"}
                    metrics.mark("request_started")
                    if acquired and client is self.vision.local:
                        response = self.vision.stream_local(messages, model=model, max_tokens=token_limit,
                                                            temperature=CHAT_TEMPERATURE, metrics=metrics, output_format=SENTENCE_SCHEMA)
                        deltas = response
                    else:
                        response = client.chat.completions.create(**kwargs)
                        deltas = (getattr(chunk.choices[0].delta, "content", "") or ""
                                  for chunk in response if chunk.choices)
                    for delta in deltas:
                        if stop_event and stop_event.is_set():
                            status = "cancelled"
                            return
                        if not delta:
                            continue
                        metrics.mark("first_chunk")
                        found = parser.feed(delta)
                        if preview_callback and not sentences:
                            preview = parser.preview()[:1200]
                            if preview:
                                metrics.mark("first_text_preview")
                                preview_callback(preview)
                        for sentence in found:
                            if not action_intent(user_input):
                                sentence.pop("action", None)
                            metrics.mark("first_sentence")
                            sentences.append(sentence)
                            yield sentence
                    if not sentences:
                        for sentence in parse_response(parser.raw)["sentences"]:
                            if not action_intent(user_input):
                                sentence.pop("action", None)
                            sentences.append(sentence)
                            metrics.mark("first_sentence")
                            yield sentence
                    if not sentences:
                        raise ValueError("模型未返回有效句子，请重试")
                    break
                except Exception as exc:
                    if not routed or client is self.client or sentences:
                        raise
                    metrics.values["local_fallback_reason"] = type(exc).__name__
                    self.vision.failed(client, model)
                finally:
                    if response and hasattr(response, "close"):
                        response.close()
            if not sentences:
                raise ValueError("所有可用模型均未返回有效回复，请重试")
            if not stop_event or not stop_event.is_set():
                if record_turn:
                    self._post_process_sentences(user_input, "", sentences, has_image)
                status = "ok"
        finally:
            if acquired:
                self.vision.release()
            if gateway and routed:
                gateway.foreground_requested.clear()
            metrics.save(status)

    def _post_process_sentences(self, user_input, full_raw, sentences, has_image=False):
        reply = "\n".join(s["text"] for s in sentences)
        if not reply:
            return
        self._opening = ""
        # Commit only successful turns; never retain images or executable actions.
        with self._history_lock:
            self.history.extend([
                {"role": "user", "content": ("[图像] " if has_image else "") + user_input},
                {"role": "assistant", "content": reply},
            ])
            self._trim_history()
        if self.memory_service and not has_image:
            try:
                self.memory_service.save(user_input, reply, sentences[0]["emotion"])
            except OSError:
                import logging
                logging.error("Memory journal write failed; reply is still available in session history")
        if has_image:
            self.observations.update(reply, "本轮视觉回答")
        state = getattr(self, "session_state", None)
        if state is not None and not has_image:
            state.remember_turn(user_input, reply)

    def set_opening(self, text, previous_context=""):
        if getattr(self, "_opening_text", None) == text:
            return
        self._opening_text = text
        self._opening = previous_context
        self.record_utterance(text)

    def record_utterance(self, text):
        """Remember greetings/proactive speech so the next user can refer to it."""
        if text.strip():
            with self._history_lock:
                self.history.append({"role": "assistant", "content": text})
                self._trim_history()

    def _trim_history(self):
        while len(self.history) > 64 or sum(len(m["content"]) for m in self.history) > 24000:
            del self.history[0]
            while self.history and self.history[0]["role"] != "user":
                del self.history[0]

    def record_action(self, result):
        self.observations.update("桌面执行结果：" + result, "桌面操作")

    def record_tool_turn(self, user_input, result):
        """Store the executor's actual outcome, never an unexecuted model promise."""
        with self._history_lock:
            self.history.extend([{"role": "user", "content": user_input},
                                 {"role": "assistant", "content": "[程序执行反馈] " + result}])
            self._trim_history()

    def vision_chat_local(self, prompt, image_b64, system="", background=False):
        messages = ([{"role": "system", "content": system}] if system else [])
        messages.append({"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + image_b64}},
        ]})
        return self.vision.complete(messages, background=background)

    def chat(self, user_input, screen_b64="", camera_b64=""):
        return {"sentences": list(self.chat_stream(user_input, screen_b64, camera_b64))}

    parse_response = staticmethod(parse_response)
    _parse_raw = staticmethod(parse_response)
    _try_extract_json = staticmethod(extract_object)

    def _sanitized_history(self):
        with self._history_lock:
            output = []
            for message in self.history:
                content = message.get("content", "")
                if isinstance(content, list):
                    content = "[图像] " + " ".join(p.get("text", "") for p in content
                                                  if isinstance(p, dict) and p.get("type") == "text")
                output.append({"role": message.get("role", "user"), "content": content})
            return output

    def clear_history(self):
        with self._history_lock:
            self.history.clear()
            self._opening = ""

    @property
    def last_reply(self):
        with self._history_lock:
            return self.history[-1]["content"] if self.history and self.history[-1]["role"] == "assistant" else ""

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self.memory_service:
            self.memory_service.close()
        self.vision.close()
        self.client.close()
