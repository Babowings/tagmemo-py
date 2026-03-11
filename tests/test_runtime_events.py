from __future__ import annotations

from fastapi.testclient import TestClient

import app as tagmemo_app
from tagmemo.runtime_events import RuntimeEventHub


def test_runtime_event_hub_snapshot_and_subscribe() -> None:
    hub = RuntimeEventHub(max_events_per_request=10, retention_seconds=1)
    hub.start_request("req-1")
    first = hub.publish("req-1", "REQUEST_START", {"message": "hello"})
    queue = hub.subscribe("req-1")
    backlog = hub.snapshot("req-1")

    assert backlog == [first]

    second = hub.publish("req-1", "TOOL_REQUEST", {"tool_name": "DailyNote"})
    assert queue.get_nowait() == second


def test_runtime_event_hub_end_request_and_prune() -> None:
    hub = RuntimeEventHub(max_events_per_request=10, retention_seconds=0)
    hub.start_request("req-2")
    hub.publish("req-2", "REQUEST_START", {})
    end_event = hub.end_request("req-2", {"status": "ok"})

    assert end_event["event_type"] == "REQUEST_END"
    assert hub.is_finished("req-2") is True

    hub.prune()
    assert hub.snapshot("req-2") == []


def test_chat_events_replays_sse_for_finished_request(monkeypatch) -> None:
    hub = RuntimeEventHub(max_events_per_request=10, retention_seconds=60)
    hub.start_request("req-finished")
    first = hub.publish("req-finished", "REQUEST_START", {"message": "hello"})
    end_event = hub.end_request("req-finished", {"status": "ok"})
    monkeypatch.setattr(tagmemo_app, "runtime_event_hub", hub)

    client = TestClient(tagmemo_app.app)
    with client.stream("GET", "/v1/chat/events", params={"request_id": "req-finished"}) as response:
        body = b"".join(response.iter_bytes())

    text = body.decode("utf-8")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert f"data: {tagmemo_app.json.dumps(first, ensure_ascii=False)}\n\n" in text
    assert f"data: {tagmemo_app.json.dumps(end_event, ensure_ascii=False)}\n\n" in text


def test_build_sse_helpers_use_real_newlines() -> None:
    data = tagmemo_app._build_sse_data({"event_type": "REQUEST_START"}).decode("utf-8")
    comment = tagmemo_app._build_sse_comment("keepalive").decode("utf-8")

    assert data.endswith("\n\n")
    assert "\\n\\n" not in data
    assert comment == ": keepalive\n\n"
