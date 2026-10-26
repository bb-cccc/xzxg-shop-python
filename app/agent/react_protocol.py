from __future__ import annotations

 

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(slots=True)
class ParsedAction:
    kind: Literal["tool", "final", "invalid"]
    tool: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    content: str = ""


TOOL_ARGUMENTS: dict[str, set[str]] = {
    "search_products": {"query", "limit", "constraints", "negative"},
    "search_knowledge": {"query", "limit"},
    "search_image_products": {"file_id", "object_key", "image_url", "limit"},
    "get_cart": set(),
    "add_cart_item": {"product_id", "sku_id", "quantity"},
    "update_cart_item": {"cart_item_id", "quantity", "selected"},
    "delete_cart_item": {"cart_item_id"},
    "preview_discount": set(),
    "checkout": set(),
    "list_orders": {"limit"},
    "get_order": {"order_id"},
    "pay_order": {"order_id", "method"},
    "cancel_order": {"order_id", "reason"},
    "confirm_receipt": {"order_id"},
    "list_coupons": {"limit"},
    "list_user_coupons": {"limit"},
    "claim_coupon": {"coupon_id"},
    "list_reviews": {"product_id", "limit"},
}


def validate_tool_arguments(tool: str, arguments: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """Sanitize model arguments before they reach a business tool."""
    allowed = TOOL_ARGUMENTS.get(tool)
    if allowed is None or not isinstance(arguments, dict):
        return False, {}
    cleaned = {key: value for key, value in arguments.items() if key in allowed}
    for key in ("query", "product_id", "sku_id", "cart_item_id", "order_id", "coupon_id", "method", "reason", "file_id", "object_key", "image_url"):
        if key in cleaned and not isinstance(cleaned[key], str):
            return False, {}
    for key in ("limit", "quantity"):
        if key in cleaned:
            if isinstance(cleaned[key], bool) or not isinstance(cleaned[key], int) or cleaned[key] < 1 or cleaned[key] > 100:
                return False, {}
    for key in ("constraints", "negative"):
        if key in cleaned and not isinstance(cleaned[key], dict):
            return False, {}
    if "selected" in cleaned and not isinstance(cleaned["selected"], bool):
        return False, {}
    return True, cleaned


def _json_object(value: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def parse_model_output(raw: str) -> ParsedAction:
    """Parse the small, backwards-compatible ReAct protocol used by the models."""
    patterns = (
        (r"<tool>\s*([A-Za-z0-9_]+)\s*</tool>.*?<tool_code>\s*(\{.*?\})\s*</tool_code>", True),
        (r"<tool>\s*([A-Za-z0-9_]+)\s*</tool>.*?<tool_input>\s*(\{.*?\})\s*</tool_input>", True),
        (r"<tool_code>\s*([A-Za-z0-9_]+)\s*</tool_code>.*?<tool_params>\s*(\{.*?\})\s*</tool_params>", True),
    )
    for pattern, _ in patterns:
        match = re.search(pattern, raw, re.DOTALL | re.IGNORECASE)
        if match:
            arguments = _json_object(match.group(2))
            if arguments is not None:
                return ParsedAction("tool", match.group(1).strip(), arguments)

    inline = re.search(r"<tool>\s*([A-Za-z0-9_]+)\s*(\{.*?\})\s*</tool>", raw, re.DOTALL | re.IGNORECASE)
    if inline:
        arguments = _json_object(inline.group(2))
        if arguments is not None:
            return ParsedAction("tool", inline.group(1).strip(), arguments)

    nested = re.search(r"<tool>\s*<([A-Za-z0-9_]+)>(.*?)</\1>\s*</tool>", raw, re.DOTALL | re.IGNORECASE)
    if nested:
        inner = nested.group(2)
        arguments: dict[str, Any] = {}
        query = re.search(r"<query>\s*(.*?)\s*</query>", inner, re.DOTALL | re.IGNORECASE)
        limit = re.search(r"<limit>\s*(\d+)\s*</limit>", inner, re.DOTALL | re.IGNORECASE)
        categories = re.findall(r"<categories>\s*(.*?)\s*</categories>", inner, re.DOTALL | re.IGNORECASE)
        if query:
            arguments["query"] = query.group(1).strip()
        if limit:
            arguments["limit"] = int(limit.group(1))
        if categories:
            arguments["constraints"] = {"categories": [item.strip() for item in categories if item.strip()]}
        return ParsedAction("tool", nested.group(1).strip(), arguments)

    wrapped = re.search(r"<tool>\s*(\{.*?\})\s*</tool>", raw, re.DOTALL | re.IGNORECASE)
    if wrapped:
        document = _json_object(wrapped.group(1))
        if document is not None:
            arguments = document.get("parameters") if isinstance(document.get("parameters"), dict) else document.get("arguments", {})
            return ParsedAction("tool", str(document.get("name") or document.get("tool") or ""), arguments if isinstance(arguments, dict) else {})

    final = re.search(r"<final>\s*(.*?)\s*</final>", raw, re.DOTALL | re.IGNORECASE)
    if final:
        return ParsedAction("final", content=final.group(1).strip())

    json_match = re.search(r"\{.*\}", raw, re.DOTALL)
    if json_match:
        document = _json_object(json_match.group(0))
        if document is not None:
            arguments = document.get("parameters") if isinstance(document.get("parameters"), dict) else document.get("arguments", {})
            if document.get("type") == "tool_call" or document.get("tool") or document.get("name"):
                return ParsedAction("tool", str(document.get("tool") or document.get("name") or ""), arguments if isinstance(arguments, dict) else {})
    return ParsedAction("invalid")
