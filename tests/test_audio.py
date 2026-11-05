import numpy as np
from core.audio import SpeechSegmenter


def test_click_noise_plus_silence_is_not_valid_speech():
    segmenter = SpeechSegmenter(16000, 0.01)
    assert segmenter.feed(np.ones(800, dtype=np.float32)) is None
    assert segmenter.feed(np.zeros(16000, dtype=np.float32)) is None


def test_voiced_speech_ends_after_short_silence_and_keeps_preroll():
    segmenter = SpeechSegmenter(16000, 0.01)
    assert segmenter.feed(np.zeros(1600, dtype=np.float32)) is None
    assert segmenter.feed(np.ones(6400, dtype=np.float32)) is None
    result = segmenter.feed(np.zeros(11200, dtype=np.float32))
    assert result is not None and len(result) == 19200


def test_continuous_noise_cannot_grow_audio_buffer_unbounded():
    segmenter = SpeechSegmenter(16000, 0.01, maximum=1)
    assert segmenter.feed(np.ones(16000, dtype=np.float32)) is not None
    assert segmenter._frames == []
