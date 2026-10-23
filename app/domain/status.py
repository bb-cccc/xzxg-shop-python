from __future__ import annotations

# 领域模型模块：定义业务实体、状态和接口数据结构。

ORDER_TRANSITIONS: dict[str, set[str]] = {
    "pending_payment": {"pending_ship", "canceled", "closed_timeout"},
    "pending_ship": {"shipped", "canceled"},
    "shipped": {"completed"},
    "completed": set(),
    "canceled": set(),
    "closed_timeout": set(),
}


def can_transition(current: str, target: str) -> bool:
    return target in ORDER_TRANSITIONS.get(current, set())
