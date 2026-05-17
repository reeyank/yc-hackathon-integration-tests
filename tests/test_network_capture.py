import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from network_capture import load_network_events, summarize  # noqa: E402


def test_loads_har_and_summarizes_failures(tmp_path):
    har = tmp_path / "capture.har"
    har.write_text(
        json.dumps(
            {
                "log": {
                    "entries": [
                        {
                            "request": {
                                "method": "POST",
                                "url": "https://api.example.test/auth",
                                "bodySize": 12,
                            },
                            "response": {"status": 500, "bodySize": 55},
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    events = load_network_events(str(har))
    summary = summarize(events)

    assert len(events) == 1
    assert summary["failures"] == 1
    assert summary["failed"][0]["host"] == "api.example.test"


def test_jsonl_loader_ignores_partial_live_proxy_lines(tmp_path):
    path = tmp_path / "network.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "method": "GET",
                        "url": "https://api.example.test/report",
                        "status": 200,
                    }
                ),
                '{"method": "POST"',
            ]
        ),
        encoding="utf-8",
    )

    events = load_network_events(str(path))

    assert len(events) == 1
    assert events[0].status == 200
