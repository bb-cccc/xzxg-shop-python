from __future__ import annotations

 

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

Emit = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass
class RuntimeResult:
    status: str = "completed"
    content: str = ""
    blocks: list[dict[str, Any]] = field(default_factory=list)
    followups: list[str] = field(default_factory=list)
    segments: list[dict[str, Any]] = field(default_factory=list)
