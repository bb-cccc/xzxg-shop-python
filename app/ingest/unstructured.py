from __future__ import annotations

# 内容导入模块：解析外部 HTML、JSON 或文本内容。

import html as html_lib
import json
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx


DEFAULT_MAX_FETCH_BYTES = 2 << 20
DEFAULT_MAX_TEXT_RUNES = 120_000
_SCRIPT_STYLE_RE = re.compile(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>")
_TAG_RE = re.compile(r"(?s)<[^>]+>")
_SPACE_RE = re.compile(r"[ \t\f\v]+")


# 模块中的核心类型，封装相关状态和行为。
@dataclass(slots=True)
class ParsedDocument:
    title: str
    doc_type: str
    content: str
    source_url: str
    metadata: dict[str, object]
    text_runes: int
    source_type: str


def _plain_text(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    lines = []
    for line in value.split("\n"):
        cleaned = _SPACE_RE.sub(" ", line.strip())
        if cleaned:
            lines.append(cleaned)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def html_to_text(value: str) -> str:
    value = _SCRIPT_STYLE_RE.sub("\n", value)
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
    return _plain_text(html_lib.unescape(_TAG_RE.sub("\n", value)))


def _flatten_json(prefix: str, value: object, lines: list[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            _flatten_json(f"{prefix}.{key}" if prefix else str(key), child, lines)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _flatten_json(f"{prefix}[{index}]", child, lines)
    elif isinstance(value, str) and value.strip():
        lines.append(f"{prefix}: {value}")
    elif isinstance(value, (float, int, bool)):
        lines.append(f"{prefix}: {value}")


def json_to_text(value: str) -> str:
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return _plain_text(value)
    lines: list[str] = []
    _flatten_json("", decoded, lines)
    return _plain_text("\n".join(lines))


def _normalize_source_type(value: str) -> str:
    lowered = value.strip().lower()
    if lowered in {"html", "web", "page"}:
        return "html"
    if lowered in {"json", "jsonl"}:
        return "json"
    return "text"


def _infer_source_type(source_url: str, body: str) -> str:
    path = urlparse(source_url).path.lower()
    if path.endswith((".json", ".jsonl")):
        return "json"
    if "<html" in body.lower() or "<body" in body.lower():
        return "html"
    return "text"


async def _fetch(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("source_url must be http or https")
    async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
        response = await client.get(url, headers={"User-Agent": "xzxg-shop-rag-ingest/1.0"})
        response.raise_for_status()
        body = response.content
    if len(body) > DEFAULT_MAX_FETCH_BYTES:
        raise ValueError("fetched document too large")
    return body.decode("utf-8", errors="replace")


async def parse(request: object) -> ParsedDocument:
    source_type = _normalize_source_type(str(getattr(request, "source_type", "text") or "text"))
    source_url = str(getattr(request, "source_url", "") or "").strip()
    raw = next((str(getattr(request, key, "") or "") for key in ("content", "html", "json_text") if str(getattr(request, key, "") or "").strip()), "")
    if not raw and source_url:
        raw = await _fetch(source_url)
        if source_type == "text":
            source_type = _infer_source_type(source_url, raw)
    if not raw.strip():
        raise ValueError("empty unstructured content")
    if source_type == "html":
        content = html_to_text(raw)
    elif source_type == "json":
        content = json_to_text(raw)
    else:
        content = _plain_text(raw)
    content = content[:DEFAULT_MAX_TEXT_RUNES]
    if not content:
        raise ValueError("empty parsed text")
    title = str(getattr(request, "title", "") or "").strip()
    if not title:
        title = content.split("\n", 1)[0][:80] or source_url or "非结构化资料"
    doc_type = {"html": "web_article", "json": "structured_note"}.get(source_type, "unstructured_note")
    return ParsedDocument(title, doc_type, content, source_url, dict(getattr(request, "metadata", {}) or {}), len(content), source_type)
