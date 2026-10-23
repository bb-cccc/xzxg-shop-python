from __future__ import annotations

# 检索增强模块：负责文本切片、关键词重排和图片索引。

from dataclasses import dataclass, field

from app.rag.tokenize import query_terms


DEFAULT_WEIGHTS = {
    # 标题命中通常比正文命中更能说明相关性，因此单独设置权重。
    "title_match": 0.35,
    "term_match": 0.45,
    "required_match": 0.20,
    "brand_boost": 0.35,
    "model_boost": 0.30,
    "category_boost": 0.15,
    "generic_penalty": 0.45,
}


@dataclass
class Candidate:
    """待重排的知识片段，保存来源信息、当前分数和扩展元数据。"""
    chunk_id: str
    title: str
    snippet: str
    source: str = ""
    score: float = 0.0
    metadata: dict[str, object] = field(default_factory=dict)


def _terms(value: str) -> list[str]:
    """提取查询词并限制数量，避免超长查询稀释每个词的影响。"""
    return query_terms(value)[:16]


def _matches(text: str, values: list[str]) -> int:
    """统计给定词列表中有多少词出现在文本里。"""
    return sum(1 for value in values if value and value in text)


def score_candidate(candidate: Candidate, query: str, required_terms: list[str] | None = None, *, brand_terms: list[str] | None = None, model_terms: list[str] | None = None, category_terms: list[str] | None = None, generic_terms: list[str] | None = None, weights: dict[str, float] | None = None) -> float:
    """按标题、普通词、必需词和业务词计算候选片段的相关性。"""
    # 允许调用方只覆盖部分权重，未提供的权重继续使用默认值。
    weights = {**DEFAULT_WEIGHTS, **(weights or {})}
    terms = _terms(query)
    required = [item.strip().lower() for item in (required_terms or []) if item.strip()]
    text = f"{candidate.title}\n{candidate.snippet}".lower()
    # 标题单独计算二值命中分，正文和标题合并后再计算普通词命中比例。
    title_score = 1.0 if any(term in candidate.title.lower() for term in terms) else 0.0
    term_ratio = _matches(text, terms) / len(terms) if terms else 0.0
    required_ratio = _matches(text, required) / len(required) if required else 0.0
    # 基础分由标题、普通查询词和必需词三部分加权组成。
    score = weights["title_match"] * title_score + weights["term_match"] * term_ratio + weights["required_match"] * required_ratio
    for key, values in (("brand_boost", brand_terms), ("model_boost", model_terms), ("category_boost", category_terms)):
        # 品牌、型号和类目属于更具体的业务词，命中后额外加分。
        if values and any(item.strip().lower() in text for item in values if item.strip()):
            score += weights[key]
    generic = [item.strip().lower() for item in (generic_terms or []) if item.strip()]
    # 只有查询全部由泛词组成、且没有命中具体业务词时才扣分。
    if generic and _matches(text, generic) == len(generic) and not any(item.strip().lower() in text for item in [*(brand_terms or []), *(model_terms or []), *(category_terms or [])] if item.strip()):
        score -= weights["generic_penalty"]
    # 对外统一限制在 0～1，避免自定义权重导致异常分数。
    return max(0.0, min(1.0, score))


def rank_candidates(candidates: list[Candidate], query: str, limit: int = 5, min_score: float = 0.0, **kwargs: object) -> list[Candidate]:
    """补充候选分数、稳定排序，并返回满足阈值的有限结果。"""
    for candidate in candidates:
        # 外部召回器已经提供分数时保留它，否则使用本地规则计算。
        if candidate.score == 0:
            candidate.score = score_candidate(candidate, query, **kwargs)
    candidates.sort(key=lambda item: (-item.score, item.chunk_id))
    # 分数相同按 chunk_id 排序，保证多次请求返回顺序稳定可复现。
    return [item for item in candidates if item.score >= min_score][: max(1, min(limit, 50))]

