import io
import httpx
from core.transport import WindowsCurlTransport


class FakeProcess:
    def __init__(self, output):
        self.stdin = io.BytesIO()
        self.stdout = io.BytesIO(output)
        self.done = False
    def poll(self):
        return 0 if self.done else None
    def wait(self, timeout=None):
        self.done = True
        return 0
    def terminate(self):
        self.done = True


def test_transport_streams_without_auth_on_command_line(monkeypatch):
    created = []
    class CapturingInput(io.BytesIO):
        def close(self):
            self.saved = self.getvalue()
    process = FakeProcess(b'HTTP/1.1 100 Continue\r\n\r\nHTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nContent-Type: text/event-stream\r\n\r\ndata: {}\n\n')
    process.stdin = CapturingInput()
    monkeypatch.setattr("core.transport.shutil.which", lambda name: "curl.exe")
    def spawn(args, **kwargs):
        created.extend(args)
        return process
    monkeypatch.setattr("core.transport.subprocess.Popen", spawn)
    adapter = WindowsCurlTransport()
    response = adapter.handle_request(httpx.Request("POST", "https://example.com", headers={
        "authorization": "Bearer secret", "content-type": "application/json"}, content=b'{"test":1}'))
    assert "secret" not in " ".join(created)
    assert b"secret" in process.stdin.saved
    assert response.status_code == 200
    assert "transfer-encoding" not in response.headers
    assert response.read() == b'data: {}\n\n'
    response.close()
