"""Windows Schannel transport for old Anaconda OpenSSL; credentials stay off argv/disk.

Modern Python uses HTTPX normally. The isolated compatibility adapter preserves
OpenAI streaming and certificate verification without replacing the application runtime.
"""
import json
import os
import shutil
import ssl
import subprocess
import tempfile
import httpx


class CurlStream(httpx.SyncByteStream):
    def __init__(self, process, body_path=None):
        self.process, self.body_path = process, body_path

    def __iter__(self):
        while True:
            chunk = self.process.stdout.read1(4096)
            if not chunk:
                break
            yield chunk
        code = self.process.wait()
        if code:
            raise httpx.ReadError("Windows HTTPS transfer failed (curl code %d)" % code)

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
        self.process.wait(timeout=5)
        self.process.stdout.close()
        if self.body_path:
            try:
                os.unlink(self.body_path)
            except OSError:
                pass


class WindowsCurlTransport(httpx.BaseTransport):
    def __init__(self, timeout=30):
        self.timeout = timeout
        self.executable = shutil.which("curl.exe")
        if not self.executable:
            raise RuntimeError("Windows curl.exe is unavailable")

    def handle_request(self, request):
        lines = ["url = " + json.dumps(str(request.url)),
                 "request = " + json.dumps(request.method),
                 "connect-timeout = 3", "max-time = " + str(self.timeout)]
        for key, value in request.headers.multi_items():
            if key.lower() not in {"host", "content-length", "accept-encoding"}:
                lines.append("header = " + json.dumps(key + ": " + value))
        body = request.read()
        body_path = None
        if body:
            if "application/json" in request.headers.get("content-type", ""):
                lines.append("data-binary = " + json.dumps(body.decode("utf-8"), ensure_ascii=False))
            else:
                with tempfile.NamedTemporaryFile(prefix="xiaole-request-", delete=False) as file:
                    file.write(body)
                    body_path = file.name
                lines.append("data-binary = " + json.dumps("@" + body_path))
        try:
            process = subprocess.Popen(
                [self.executable, "-q", "--config", "-", "--silent", "--show-error", "--include", "--no-buffer"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as exc:
            if body_path:
                os.unlink(body_path)
            raise httpx.ConnectError("Windows HTTPS transport could not start", request=request) from exc
        stream = CurlStream(process, body_path)
        try:
            process.stdin.write(("\n".join(lines) + "\n").encode("utf-8"))
            process.stdin.close()
            while True:
                status = process.stdout.readline().decode("latin1").strip()
                if not status.startswith("HTTP/"):
                    raise httpx.ConnectError("Windows HTTPS connection failed", request=request)
                code = int(status.split()[1])
                headers = []
                while True:
                    line = process.stdout.readline()
                    if line in {b"\r\n", b"\n", b""}:
                        break
                    key, value = line.decode("latin1").split(":", 1)
                    headers.append((key.strip(), value.strip()))
                if code >= 200:
                    # curl removes HTTP chunk framing, so these headers no longer apply.
                    headers = [(k, v) for k, v in headers if k.lower() not in {"transfer-encoding", "content-encoding"}]
                    return httpx.Response(code, headers=headers, stream=stream, request=request)
        except Exception:
            stream.close()
            raise


def cloud_http_client(timeout=30):
    mode = os.getenv("CLOUD_TRANSPORT", "auto").lower()
    legacy_windows = os.name == "nt" and ssl.OPENSSL_VERSION_INFO < (1, 1, 2)
    transport = WindowsCurlTransport(timeout) if mode == "windows" or (mode == "auto" and legacy_windows) else None
    return httpx.Client(transport=transport, timeout=httpx.Timeout(timeout, connect=3))
