"""Streaming JSON sentence extraction, including legacy wrapped arrays."""
import json
import re

EMOTIONS = {"neutral", "happy", "sad", "surprised", "angry", "thinking", "shy"}
ACTION_SCHEMA = {"anyOf": [
    {"type": "object", "properties": {"type": {"const": "open"}, "target": {"type": "string", "minLength": 1}},
     "required": ["type", "target"], "additionalProperties": False},
    {"type": "object", "properties": {"type": {"const": "search"}, "query": {"type": "string", "minLength": 1},
     "engine": {"enum": ["google", "bing", "baidu", "wikipedia"]}, "open_first": {"type": "boolean"}},
     "required": ["type", "query"], "additionalProperties": False},
    {"type": "object", "properties": {"type": {"const": "click"}, "x": {"type": "number"}, "y": {"type": "number"},
     "button": {"enum": ["left", "right", "middle"]}}, "required": ["type", "x", "y"], "additionalProperties": False},
    {"type": "object", "properties": {"type": {"const": "type"}, "text": {"type": "string", "minLength": 1, "maxLength": 2000}},
     "required": ["type", "text"], "additionalProperties": False},
    {"type": "object", "properties": {"type": {"const": "hotkey"}, "keys": {"type": "array", "minItems": 1, "items": {"type": "string"}}},
     "required": ["type", "keys"], "additionalProperties": False},
    {"type": "object", "properties": {"type": {"const": "scroll"}, "direction": {"enum": ["up", "down"]},
     "amount": {"type": "integer", "minimum": 1, "maximum": 20}}, "required": ["type", "direction"], "additionalProperties": False},
]}
SENTENCE_SCHEMA = {
    "type": "object",
    "properties": {"sentences": {"type": "array", "minItems": 1, "maxItems": 12,
        "items": {"type": "object", "properties": {
            "text": {"type": "string", "minLength": 1},
            "emotion": {"type": "string", "enum": sorted(EMOTIONS)},
            "action": ACTION_SCHEMA},
            "required": ["text", "emotion"], "additionalProperties": False}}},
    "required": ["sentences"], "additionalProperties": False,
}


def normalize_sentence(obj, allow_action=True):
    if not isinstance(obj, dict) or not isinstance(obj.get("text"), str):
        return None
    text = obj["text"].strip()
    if not text:
        return None
    result = {"text": text[:1200], "emotion": obj.get("emotion", "neutral")}
    if not isinstance(result["emotion"], str) or result["emotion"] not in EMOTIONS:
        result["emotion"] = "neutral"
    if allow_action and isinstance(obj.get("action"), dict):
        result["action"] = obj["action"]
    return result


class SentenceParser:
    """Scan each character once; emit inner sentence objects before wrapper closure."""
    def __init__(self):
        self.raw = ""
        self._stack = []
        self._in_string = False
        self._escape = False

    def feed(self, delta):
        offset = len(self.raw)
        self.raw += delta
        output = []
        for index, char in enumerate(delta, offset):
            if self._in_string:
                if self._escape:
                    self._escape = False
                elif char == "\\":
                    self._escape = True
                elif char == '"':
                    self._in_string = False
                continue
            if char == '"':
                self._in_string = True
            elif char == "{":
                self._stack.append(index)
            elif char == "}" and self._stack:
                start = self._stack.pop()
                try:
                    obj = json.loads(self.raw[start:index + 1])
                except json.JSONDecodeError:
                    continue
                # An action may itself contain text; never emit that nested object as speech.
                nested_action = any(re.search(r'"action"\s*:\s*$', self.raw[:parent].rstrip())
                                    for parent in [start, *self._stack])
                sentence = normalize_sentence(obj)
                if sentence and not nested_action:
                    output.append(sentence)
        return output

    def preview(self):
        """Decode only the first text field, never expose JSON syntax or run an action."""
        match = re.search(r'"text"\s*:\s*"((?:\\.|[^"\\])*)', self.raw)
        if not match:
            # Some models answer in plain speech despite the format request. Preview
            # only an unambiguous prose prefix, never JSON, code or reasoning markup.
            plain = self.raw.lstrip()
            if not plain or not plain[0].isalpha():
                return ""
            if any(word.startswith(plain.lower()) for word in ("null", "none", "json")):
                return ""
            if plain.lower().startswith(("null", "none", "json")):
                return ""
            return re.split(r'[{}\[\]`<>]', plain, maxsplit=1)[0].rstrip()
        action = re.search(r'"action"\s*:', self.raw)
        if action and action.start() < match.start():
            return ""
        fragment = match.group(1)
        for trim in range(min(7, len(fragment) + 1)):
            value = fragment[:len(fragment) - trim] if trim else fragment
            try:
                return json.loads('"' + value + '"')
            except json.JSONDecodeError:
                pass
        return ""


def parse_response(raw):
    parser = SentenceParser()
    sentences = parser.feed(raw or "")
    if not sentences and raw and raw.strip().lower() not in {"null", "none"} and not raw.lstrip().startswith(("{", "[", "```")):
        sentences = [{"text": raw.strip()[:1200], "emotion": "neutral"}]
    return {"sentences": sentences}


def extract_object(buffer):
    """Compatibility helper for diagnostic scripts; returns first complete outer object."""
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", buffer):
        try:
            obj, end = decoder.raw_decode(buffer, match.start())
            return obj, end
        except json.JSONDecodeError:
            continue
    return None, 0
