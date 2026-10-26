from __future__ import annotations

 

import json
from typing import Any


def event(
    event_type: str,
    run_id: str,
    *,
    session_id: str = "",
    user_message_id: str = "",
    trace_id: str = "",
    stage: str = "",
    text: str = "",
    delta: str = "",
    block: dict[str, Any] | None = None,
    part: dict[str, Any] | None = None,
    step: dict[str, Any] | None = None,
    questions: list[str] | None = None,
    code: str = "",
    message: str = "",
) -> dict[str, Any]:
    payload: dict[str, Any] = {"type": event_type}
    for key, value in {
        "run_id": run_id,
        "session_id": session_id,
        "user_message_id": user_message_id,
        "trace_id": trace_id,
        "stage": stage,
        "text": text,
        "delta": delta,
        "block": block,
        "part": part,
        "step": step,
        "questions": questions,
        "code": code,
        "message": message,
    }.items():
        if value not in (None, "", [], {}):
            payload[key] = value
    return payload


def sse_encode(payload: dict[str, Any]) -> str:
    return f"event: {payload['type']}\ndata: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"
