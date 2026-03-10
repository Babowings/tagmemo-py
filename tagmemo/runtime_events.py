from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class _RequestEventState:
    events: deque[dict[str, Any]] = field(default_factory=deque)
    subscribers: set[asyncio.Queue] = field(default_factory=set)
    sequence: int = 0
    finished: bool = False
    created_at: float = field(default_factory=time.monotonic)
    last_seen: float = field(default_factory=time.monotonic)


class RuntimeEventHub:
    def __init__(self, *, max_events_per_request: int = 200, retention_seconds: float = 600.0) -> None:
        self.max_events_per_request = max_events_per_request
        self.retention_seconds = retention_seconds
        self._requests: dict[str, _RequestEventState] = {}

    def start_request(self, request_id: str) -> None:
        state = self._requests.get(request_id)
        if state is None:
            self._requests[request_id] = _RequestEventState(
                events=deque(maxlen=self.max_events_per_request),
            )
            return
        state.finished = False
        state.last_seen = time.monotonic()

    def publish(self, request_id: str, event_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        state = self._requests.get(request_id)
        if state is None:
            state = _RequestEventState(events=deque(maxlen=self.max_events_per_request))
            self._requests[request_id] = state

        state.sequence += 1
        state.last_seen = time.monotonic()
        event = {
            "request_id": request_id,
            "seq": state.sequence,
            "timestamp": time.time(),
            "event_type": event_type,
            "payload": payload or {},
        }
        state.events.append(event)
        for subscriber in list(state.subscribers):
            try:
                subscriber.put_nowait(event)
            except asyncio.QueueFull:
                continue
        return event

    def end_request(self, request_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        state = self._requests.get(request_id)
        if state is None:
            self.start_request(request_id)
            state = self._requests[request_id]
        state.finished = True
        state.last_seen = time.monotonic()
        return self.publish(request_id, "REQUEST_END", payload)

    def snapshot(self, request_id: str) -> list[dict[str, Any]]:
        state = self._requests.get(request_id)
        if state is None:
            return []
        state.last_seen = time.monotonic()
        return list(state.events)

    def is_finished(self, request_id: str) -> bool:
        state = self._requests.get(request_id)
        return bool(state.finished) if state else False

    def subscribe(self, request_id: str, *, queue_size: int = 200) -> asyncio.Queue:
        state = self._requests.get(request_id)
        if state is None:
            self.start_request(request_id)
            state = self._requests[request_id]
        queue: asyncio.Queue = asyncio.Queue(maxsize=queue_size)
        state.subscribers.add(queue)
        state.last_seen = time.monotonic()
        return queue

    def unsubscribe(self, request_id: str, queue: asyncio.Queue) -> None:
        state = self._requests.get(request_id)
        if state is None:
            return
        state.subscribers.discard(queue)
        state.last_seen = time.monotonic()

    def prune(self) -> None:
        now = time.monotonic()
        expired = [
            request_id
            for request_id, state in self._requests.items()
            if state.finished and not state.subscribers and (now - state.last_seen) >= self.retention_seconds
        ]
        for request_id in expired:
            self._requests.pop(request_id, None)