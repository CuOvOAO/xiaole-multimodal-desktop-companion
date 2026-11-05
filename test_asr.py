"""ASR endpoint check using synthetic audio, never opens the microphone."""
import io
import wave
from pathlib import Path
import numpy as np
from core.asr import ASRListener

cache = Path.home() / ".cache" / "huggingface" / "hub" / "models--mobiuslabsgmbh--faster-whisper-large-v3-turbo"
unfinished = list(cache.glob("**/*.incomplete")) if cache.exists() else []
print("Whisper cache unfinished files:", len(unfinished))
print("Cache inspection does not prove Whisper can load; the application currently uses online ASR.")
listener = ASRListener(on_text=lambda text: None)
samples = (0.2 * np.sin(2 * np.pi * 440 * np.arange(16000) / 16000)).astype(np.float32)
try:
    response = listener._call_asr_api(listener._to_wav_bytes(samples))
    print("ASR endpoint HTTP:", response.status_code)
    if response.status_code == 200:
        print("Endpoint and authentication work; synthetic tone is NOT a speech accuracy test.")
    else:
        print("ASR endpoint unavailable; check account/model/network settings.")
finally:
    listener._session.close()
