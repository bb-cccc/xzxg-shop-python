from __future__ import annotations

# 查询关键词提取。
# 输入是一句自然语言查询，输出是去重后的关键词列表。
# 先统一大小写和空白，再过滤无意义字符。
# 关键词是后续候选召回和评分的共同输入。

# 查询分词模块：提取并去重查询中的关键词。

import re


def query_terms(query: str) -> list[str]:
    """提取查询词并去重；中文补充 2~4 字窗口，英文数字保留完整片段。"""
    # result 保持首次出现顺序，seen 防止重复词放大评分。
    result: list[str] = []
    seen: set[str] = set()
    # 正则同时识别连续中文与连续英文/数字。
    for part in re.findall(r"[\u4e00-\u9fff]+|[A-Za-z0-9]+", query or ""):
        # 中文长片段生成滑动窗口，兼顾完整词和局部商品名。
        if all("\u4e00" <= char <= "\u9fff" for char in part):
            values = [part] if len(part) <= 4 else []
            values.extend(
                part[index : index + size]
                for size in range(2, 5)
                for index in range(len(part) - size + 1)
            )
        else:
            # 英文和数字通常是品牌、型号或版本号，不再拆分。
            values = [part]
        for value in values:
            # 统一大小写，并过滤单字符噪声。
            value = value.strip().lower()
            if len(value) >= 2 and value not in seen:
                seen.add(value)
                result.append(value)
    return result

