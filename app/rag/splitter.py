from __future__ import annotations

# 文档切片。
# 输入是长文档，输出是带顺序、标题和来源信息的短片段。
# 片段过长时切开，overlap 保留相邻片段的上下文。
# 切片太小会丢上下文，太大则会增加检索和模型上下文成本。

# 文档切片模块：按长度切分文本，并保留上下文重叠。

import re

DEFAULT_CHUNK_MAX_CHARS = 800
DEFAULT_CHUNK_OVERLAP = 100
DEFAULT_SNIPPET_CHARS = 160


def clean_text(value: str) -> str:
    """统一换行、清理每行空白，并压缩连续空行。"""
    text = (value or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def snippet(value: str, max_chars: int = DEFAULT_SNIPPET_CHARS) -> str:
    """截取用于检索展示的短摘要。"""
    return (value or "").strip()[: max(1, max_chars)]


def _overlap_tail(value: str, overlap: int = DEFAULT_CHUNK_OVERLAP) -> str:
    """提取文本尾部，作为下一片段的上下文前缀。"""
    text = value.strip()
    return text[-overlap:] + "\n" if len(text) > overlap else text


def _fixed_split(value: str, max_chars: int) -> list[str]:
    """在没有自然分隔符时按固定窗口切片。"""
    text = value.strip()
    result: list[str] = []
    start = 0
    while start < len(text):
        # 当前窗口最多读取 max_chars 个字符。
        end = min(start + max_chars, len(text))
        result.append(text[start:end].strip())
        if end >= len(text):
            break
        # 向后回退 overlap，使相邻片段保留上下文。
        start = max(0, end - DEFAULT_CHUNK_OVERLAP)
    return [item for item in result if item]


def _merge_parts(parts: list[str], separator: str, max_chars: int) -> list[str]:
    """合并短分段，超过上限时输出当前片段并携带尾部重叠内容。"""
    result: list[str] = []
    current = ""
    for raw in parts:
        # 忽略空分段，避免产生空知识块。
        part = raw.strip()
        if not part:
            continue
        if separator != "\n":
            # split 移除了分隔符，这里恢复标点以保持原文语义。
            part += separator
        candidate = current + part
        if not current or len(candidate) <= max_chars:
            # 未超过限制，继续累积到当前片段。
            current = candidate
            continue
        result.append(current.strip())
        # 新片段继承旧片段尾部，降低边界切断造成的信息损失。
        current = _overlap_tail(current) + part
    if current.strip():
        result.append(current.strip())
    return result


def recursive_split(value: str, max_chars: int = DEFAULT_CHUNK_MAX_CHARS) -> list[str]:
    """按由粗到细的标点递归切分，尽量在自然语义边界断开。"""
    text = value.strip()
    if len(text) <= max_chars:
        return [text] if text else []
    for separator in ("。", "？", "！", "；", "\n", "，", "、"):
        # 优先句末标点，无法切分时逐步降级到更细的分隔符。
        parts = text.split(separator)
        if len(parts) <= 1:
            continue
        merged = _merge_parts(parts, separator, max_chars)
        output: list[str] = []
        for item in merged:
            # 合并结果仍超长时递归处理，直到满足 max_chars。
            output.extend(recursive_split(item, max_chars) if len(item) > max_chars else [item])
        return output
    return _fixed_split(text, max_chars)


def _draft(title: str, content: str, index: int) -> dict[str, object]:
    """构造统一的片段字典，供后续持久化或索引使用。"""
    text = content.strip()
    return {"title": title, "content": text, "snippet": snippet(text), "sort_order": (index + 1) * 10}


def _split_faq(title: str, content: str) -> list[dict[str, object]]:
    """识别 FAQ 问答行，并将每组问答切成独立片段。"""
    chunks: list[dict[str, object]] = []
    question = ""
    answer: list[str] = []

    def flush() -> None:
        """把当前问答缓冲区落成片段并清空答案。"""
        nonlocal question, answer
        if not question or not answer:
            return
        text = question + "\n" + "\n".join(answer)
        for part in recursive_split(text):
            chunks.append(_draft(f"{title} / FAQ", part, len(chunks)))
        answer = []

    for line in content.split("\n"):
        # Q/A 行开启或延续一组问答，其余非空行视为答案续行。
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
    """按文档类型切片：FAQ 保留问答结构，普通文档按段落和标点处理。
        对外完整流程是：清理文本 -> FAQ 特殊处理 -> 按空行分段 -> 递归切割 -> 生成结构化 chunk。
        空文档返回空列表；普通文档即使没有切成多块，也保证至少返回一个 chunk。
    """
    cleaned = clean_text(content)
    if not cleaned:
        return []
    if doc_type.strip().lower() == "faq":
        # FAQ 识别成功后直接返回，避免问答关系被普通切片拆散。
        faq = _split_faq(title.strip(), cleaned)
        if faq:
            return faq
    result: list[dict[str, object]] = []
    for block in (part.strip() for part in cleaned.split("\n\n")):
        # 普通文档先按空行分成段落，再对超长段落递归切分。
        if not block:
            continue
        for part in recursive_split(block):
            result.append(_draft(title.strip(), part, len(result)))
    return result or [_draft(title.strip(), cleaned, 0)]

