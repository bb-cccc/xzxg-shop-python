from __future__ import annotations

# 检索增强模块：负责文本切片、关键词重排和图片索引。

import re

DEFAULT_CHUNK_MAX_CHARS = 800
DEFAULT_CHUNK_OVERLAP = 100
DEFAULT_SNIPPET_CHARS = 160


def clean_text(value: str) -> str:
    text = (value or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def snippet(value: str, max_chars: int = DEFAULT_SNIPPET_CHARS) -> str:
    return (value or "").strip()[: max(1, max_chars)]


def _overlap_tail(value: str, overlap: int = DEFAULT_CHUNK_OVERLAP) -> str:
    text = value.strip()
    return text[-overlap:] + "\n" if len(text) > overlap else text


def _fixed_split(value: str, max_chars: int) -> list[str]:
    text = value.strip()
    result: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        result.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(0, end - DEFAULT_CHUNK_OVERLAP)
    return [item for item in result if item]


def _merge_parts(parts: list[str], separator: str, max_chars: int) -> list[str]:
    result: list[str] = []
    current = ""
    for raw in parts:
        part = raw.strip()
        if not part:
            continue
        if separator != "\n":
            part += separator
        candidate = current + part
        if not current or len(candidate) <= max_chars:
            current = candidate
            continue
        result.append(current.strip())
        current = _overlap_tail(current) + part
    if current.strip():
        result.append(current.strip())
    return result


def recursive_split(value: str, max_chars: int = DEFAULT_CHUNK_MAX_CHARS) -> list[str]:
    text = value.strip()
    if len(text) <= max_chars:
        return [text] if text else []
    for separator in ("。", "？", "！", "；", "\n", "，", "、"):
        parts = text.split(separator)
        if len(parts) <= 1:
            continue
        merged = _merge_parts(parts, separator, max_chars)
        output: list[str] = []
        for item in merged:
            output.extend(recursive_split(item, max_chars) if len(item) > max_chars else [item])
        return output
    return _fixed_split(text, max_chars)


def _draft(title: str, content: str, index: int) -> dict[str, object]:
    text = content.strip()
    return {"title": title, "content": text, "snippet": snippet(text), "sort_order": (index + 1) * 10}


def _split_faq(title: str, content: str) -> list[dict[str, object]]:
    chunks: list[dict[str, object]] = []
    question = ""
    answer: list[str] = []

    def flush() -> None:
        nonlocal question, answer
        if not question or not answer:
            return
        text = question + "\n" + "\n".join(answer)
        for part in recursive_split(text):
            chunks.append(_draft(f"{title} / FAQ", part, len(chunks)))
        answer = []

    for line in content.split("\n"):
        trimmed = line.strip()
        if trimmed.startswith(("Q:", "问：", "问题：")):
            flush()
            question = trimmed
        elif trimmed.startswith(("A:", "答：", "答案：")):
            answer.append(trimmed)
        elif question and trimmed:
            answer.append(trimmed)
    flush()
    return chunks


def split_document(title: str, content: str, doc_type: str = "") -> list[dict[str, object]]:
    cleaned = clean_text(content)
    if not cleaned:
        return []
    if doc_type.strip().lower() == "faq":
        faq = _split_faq(title.strip(), cleaned)
        if faq:
            return faq
    result: list[dict[str, object]] = []
    for block in (part.strip() for part in cleaned.split("\n\n")):
        if not block:
            continue
        for part in recursive_split(block):
            result.append(_draft(title.strip(), part, len(result)))
    return result or [_draft(title.strip(), cleaned, 0)]

