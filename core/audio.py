"""Pure audio segmentation, testable without a microphone or ASR service."""
from collections import deque
import numpy as np


class SpeechSegmenter:
    def __init__(self, sample_rate, threshold, silence=0.65, minimum=0.25, maximum=15.0):
        self.sample_rate, self.threshold = sample_rate, threshold
        self.silence, self.minimum, self.maximum = silence, minimum, maximum
        self._pre = deque()
        self._pre_samples = 0
        self._frames = []
        self._voiced = self._quiet = self._total = 0.0

    def feed(self, audio):
        duration = len(audio) / self.sample_rate
        voice = float(np.sqrt(np.mean(np.square(audio)))) > self.threshold
        if not self._frames and not voice:
            self._pre.append(audio)
            self._pre_samples += len(audio)
            while self._pre_samples > self.sample_rate * 0.2 and len(self._pre) > 1:
                self._pre_samples -= len(self._pre.popleft())
            return None
        if not self._frames:
            self._frames = list(self._pre)
            self._pre.clear()
            self._pre_samples = 0
        self._frames.append(audio)
        self._total += duration
        self._voiced += duration if voice else 0
        self._quiet = 0 if voice else self._quiet + duration
        if self._quiet < self.silence and self._total < self.maximum:
            return None
        result = np.concatenate(self._frames) if self._voiced >= self.minimum else None
        self._frames = []
        self._voiced = self._quiet = self._total = 0.0
        return result
