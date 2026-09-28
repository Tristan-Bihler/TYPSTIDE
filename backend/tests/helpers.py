"""Shared test helpers."""

from typing import Any

from starlette.testclient import WebSocketTestSession

FRONTEND_ORIGIN = "http://127.0.0.1:5173"


def receive_until(ws: WebSocketTestSession, message_type: str, limit: int = 20) -> dict[str, Any]:
    """Read WebSocket messages until one of `message_type` arrives."""
    for _ in range(limit):
        message: dict[str, Any] = ws.receive_json()
        if message["type"] == message_type:
            return message
    raise AssertionError(f"no {message_type} message within {limit} messages")


def receive_compile(ws: WebSocketTestSession) -> dict[str, dict[str, Any]]:
    """Collect messages of one compile cycle up to its final compile_status."""
    collected: dict[str, Any] = {}
    for _ in range(20):
        message = ws.receive_json()
        if message["type"] == "compile_status" and message["state"] == "compiling":
            continue
        collected[message["type"]] = message
        if message["type"] == "compile_status":
            return collected
    raise AssertionError("compile did not finish")
