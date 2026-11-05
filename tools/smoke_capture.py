"""Capture health check; reports dimensions only, never saves or uploads desktop pixels."""
import base64
import io
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.screen import ScreenCapture
from PIL import Image

start = time.perf_counter()
capture = ScreenCapture()
image = capture.capture_b64()
with Image.open(io.BytesIO(base64.b64decode(image))) as source:
    print("screen", source.size, source.format, "bytes", len(image),
          "ms", round((time.perf_counter() - start) * 1000))
