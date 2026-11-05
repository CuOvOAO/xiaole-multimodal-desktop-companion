import io
import wave

import numpy as np

from core.asr import ASRListener, SAMPLE_RATE


def test_native_microphone_rate_is_resampled_to_16khz_wav():
    listener = ASRListener(on_text=lambda _text: None)
    listener._input_sample_rate = 44100
    source = np.zeros(44100, dtype=np.float32)

    wav_bytes = listener._to_wav_bytes(source)

    with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
        assert wav_file.getframerate() == SAMPLE_RATE
        assert wav_file.getnchannels() == 1
        assert abs(wav_file.getnframes() - SAMPLE_RATE) <= 1
