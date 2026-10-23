from __future__ import annotations

# 检索增强模块：负责文本切片、关键词重排和图片索引。

import re


def query_terms(query: str) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for part in re.findall(r"[\u4e00-\u9fff]+|[A-Za-z0-9]+", query or ""):
        if all("\u4e00" <= char <= "\u9fff" for char in part):
            values = [part] if len(part) <= 4 else []
            values.extend(part[index : index + size] for size in range(2, 5) for index in range(len(part) - size + 1))
        else:
            values = [part]
        for value in values:
            value = value.strip().lower()
            if len(value) >= 2 and value not in seen:
                seen.add(value)
                result.append(value)
    return result

