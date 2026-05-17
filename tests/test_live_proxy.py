import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest  # noqa: E402

from live_proxy import LiveProxyCapture, LiveProxyUnavailable  # noqa: E402


def test_live_proxy_reports_missing_backend(tmp_path):
    capture = LiveProxyCapture(
        str(tmp_path / "network.jsonl"),
        binary="definitely-not-a-real-mitmdump-binary",
    )

    with pytest.raises(LiveProxyUnavailable) as exc:
        capture.start()

    assert "mitmdump is required" in str(exc.value)


def test_live_proxy_loads_captured_jsonl(tmp_path):
    out = tmp_path / "network.jsonl"
    out.write_text(
        '{"method": "GET", "url": "https://api.example.test", "status": 204}\n',
        encoding="utf-8",
    )
    capture = LiveProxyCapture(str(out))

    events = capture.events()

    assert len(events) == 1
    assert events[0].status == 204
