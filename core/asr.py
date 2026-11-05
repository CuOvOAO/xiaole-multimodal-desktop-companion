# core/asr.py — 语音识别模块（SiliconFlow 在线 ASR）
#
# 使用在线识别；采集、断句、请求互不阻塞，UI 通过信号接收转写。

from __future__ import annotations
import io
import wave
import threading
import queue
import time
import math
import numpy as np
import httpx
from core.transport import cloud_http_client
from typing import Callable, Optional

from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL

try:
    import sounddevice as sd
    _SD_OK = True
except ImportError:
    _SD_OK = False
    print("[ASR] 警告：sounddevice 未安装。pip install sounddevice")


SAMPLE_RATE = 16000
CHUNK = 512
SILENCE_DURATION = 0.65     # 较短端点等待；不计入有效说话时长
MIN_SPEECH_DURATION = 0.3   # 最短有效说话时长，过滤误触
CALIBRATE_SECONDS = 3.0     # 启动时静音校准时长
NOISE_MULTIPLIER = 3.0      # 阈值 = 环境噪音均值 × 此倍数
DEBUG_VOLUME = False        # 需要调试麦克风时可临时改为 True

ASR_URL = f"{DEEPSEEK_BASE_URL}/audio/transcriptions"
ASR_MODEL = "FunAudioLLM/SenseVoiceSmall"


class ASRListener:
    """
    持续监听麦克风，检测说话，调用 SiliconFlow ASR 识别后通过回调返回文字。

    on_text(text) 回调在后台线程调用，调用方负责线程安全。
    """

    def __init__(
        self,
        on_text: Callable[[str], None],
        language: str = "zh",
    ):
        self.on_text = on_text
        self.language = language
        self._running = False
        self._audio_queue: queue.Queue = queue.Queue(maxsize=2)
        self._silence_threshold: float = 0.005  # 校准前的保守默认值
        self._input_sample_rate = SAMPLE_RATE
        self._session = cloud_http_client(15)

    # ── 启动/停止 ─────────────────────────────────────────
    def start(self):
        if not _SD_OK:
            print("[ASR] sounddevice 未安装，语音识别不可用")
            return
        if not DEEPSEEK_API_KEY:
            print("[ASR] 未配置 API Key，语音识别不可用")
            return
        if self._running:
            return

        self._running = True
        if self._session.is_closed:
            self._session = cloud_http_client(15)

        def _background():
            self._print_mic_info()
            self._calibrate_noise()          # 在线方案无模型加载，启动几乎瞬时
            recog = threading.Thread(target=self._recog_loop, daemon=True)
            recog.start()
            self._listen_loop()              # 阻塞直到 stop()

        threading.Thread(target=_background, daemon=True).start()

    def stop(self):
        self._running = False
        print("[ASR] 语音识别已停止")

    # ── 打印当前麦克风设备 ────────────────────────────────
    def _print_mic_info(self):
        try:
            device_info = sd.query_devices(kind="input")
            name = device_info.get("name", "未知")
            sr = int(device_info.get("default_samplerate") or SAMPLE_RATE)
            self._input_sample_rate = sr
            print(
                f"[ASR] 使用麦克风：{name}（以设备原生 {sr} Hz 录音，"
                f"发送前重采样到 {SAMPLE_RATE} Hz）"
            )
        except Exception as e:
            print(f"[ASR] 获取麦克风信息失败：{e}")

    # ── 环境噪音自适应校准 ───────────────────────────────
    def _calibrate_noise(self):
        print(f"[ASR] 正在校准环境噪音，请保持安静 {int(CALIBRATE_SECONDS)} 秒...")
        samples = []
        done = threading.Event()

        def callback(indata, frames, time_info, status):
            samples.append(float(np.sqrt(np.mean(np.square(indata[:, 0])))))
            if len(samples) * CHUNK / self._input_sample_rate >= CALIBRATE_SECONDS:
                done.set()

        try:
            with sd.InputStream(
                samplerate=self._input_sample_rate,
                channels=1,
                dtype="float32",
                blocksize=CHUNK,
                callback=callback,
            ):
                done.wait(timeout=CALIBRATE_SECONDS + 2)
        except Exception as e:
            print(f"[ASR] 校准失败（使用默认阈值）：{e}")
            return

        if samples:
            baseline = float(np.percentile(samples, 60))
            self._silence_threshold = max(baseline * NOISE_MULTIPLIER, 0.002)
            print(f"[ASR] 环境噪音基准 {baseline:.4f}，识别阈值设为 {self._silence_threshold:.4f}")
        print("[ASR] 语音识别已启动，开始监听麦克风")

    # ── 麦克风监听循环 ────────────────────────────────────
    def _listen_loop(self):
        from core.audio import SpeechSegmenter
        blocks = queue.Queue(maxsize=128)
        segmenter = SpeechSegmenter(self._input_sample_rate, self._silence_threshold,
                                    silence=SILENCE_DURATION, minimum=MIN_SPEECH_DURATION)

        def callback(indata, frames, time_info, status):
            # Real-time callback does no concatenation, network I/O or terminal printing.
            try:
                blocks.put_nowait(indata[:, 0].copy())
            except queue.Full:
                pass

        try:
            with sd.InputStream(samplerate=self._input_sample_rate, channels=1, dtype="float32",
                                blocksize=CHUNK, callback=callback):
                while self._running:
                    try:
                        audio = blocks.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    if DEBUG_VOLUME:
                        print("[ASR] RMS %.4f" % np.sqrt(np.mean(np.square(audio))))
                    utterance = segmenter.feed(audio)
                    if utterance is None:
                        continue
                    if self._audio_queue.full():
                        try:
                            self._audio_queue.get_nowait()
                        except queue.Empty:
                            pass
                    self._audio_queue.put_nowait((time.monotonic(), utterance.astype(np.float32)))
        except Exception as exc:
            print("[ASR] 监听异常：" + type(exc).__name__)
        finally:
            self._running = False

    # ── float32 音频 → WAV 字节 ──────────────────────────
    def _to_wav_bytes(self, audio: np.ndarray) -> bytes:
        if self._input_sample_rate != SAMPLE_RATE and len(audio) > 1:
            from scipy.signal import resample_poly
            divisor = math.gcd(SAMPLE_RATE, self._input_sample_rate)
            audio = resample_poly(audio, SAMPLE_RATE // divisor, self._input_sample_rate // divisor).astype(np.float32)
        pcm = np.clip(audio, -1.0, 1.0)
        pcm = (pcm * 32767).astype(np.int16)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(pcm.tobytes())
        return buf.getvalue()

    # ── 发送一次 ASR 请求（可能失败）───────────────────────
    def _call_asr_api(self, wav_bytes: bytes) -> httpx.Response:
        return self._session.post(
            ASR_URL,
            headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
            files={"file": ("speech.wav", wav_bytes, "audio/wav")},
            data={"model": ASR_MODEL, "language": self.language},
            timeout=(3, 15),
        )

    # ── 识别循环（调用在线 API，失败重试一次）─────────────
    def _recog_loop(self):
        import time as _time
        while self._running:
            try:
                captured_at, audio = self._audio_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            if time.monotonic() - captured_at > 20:
                continue
            try:
                wav_bytes = self._to_wav_bytes(audio)

                resp = None
                for attempt in range(2):
                    if not self._running:
                        break
                    try:
                        candidate = self._call_asr_api(wav_bytes)
                        if candidate.status_code == 200:
                            resp = candidate
                            break
                        detail = candidate.text[:200]
                        print(
                            f"\n[ASR] API 错误 {candidate.status_code}：{detail}"
                        )
                        if candidate.status_code < 500 and candidate.status_code != 429:
                            break
                    except httpx.RequestError as exc:
                        print(f"\n[ASR] 网络请求失败：{exc}")
                    if attempt == 0:
                        print("[ASR] 0.5 秒后重试...")
                        _time.sleep(0.5)

                if resp is None:
                    print("[ASR] 识别请求未成功，丢弃本段音频")
                    continue

                text = (resp.json().get("text") or "").strip()
                if text and self._running and time.monotonic() - captured_at <= 30:
                    print(f"\n[ASR] 识别结果：{text}")
                    self.on_text(text)
            except Exception as e:
                print(f"\n[ASR] 识别失败：{e}")


# ── 模块级单例 ────────────────────────────────────────────
_listener: Optional[ASRListener] = None

def get_asr_listener(on_text: Callable[[str], None]) -> ASRListener:
    global _listener
    if _listener is None:
        _listener = ASRListener(on_text=on_text)
    else:
        _listener.on_text = on_text
    return _listener
