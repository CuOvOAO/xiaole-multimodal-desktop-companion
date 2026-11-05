import pytest


@pytest.fixture(autouse=True)
def isolate_test_metrics(monkeypatch, tmp_path):
    # Synthetic sub-millisecond streams must not pollute real user latency reports.
    monkeypatch.setattr("core.metrics.PERF_PATH", tmp_path / "performance.jsonl")
