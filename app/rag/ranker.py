from __future__ import annotations

# 候选文档重排。
# 输入是查询和候选片段，输出是按分数从高到低排列的候选。
# 标题、关键词和正文命中可以使用不同权重。
# 排序只负责相关性，不负责生成答案。

# 关键词重排模块：按命中情况为候选文档计算分数。

from dataclasses import dataclass, field

from app.rag.tokenize import query_terms

# 权重是不同命中因素的重要程度
DEFAULT_WEIGHTS = {
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
    """待重排的知识片段及其来源、分数和扩展元数据。"""
    chunk_id: str
    title: str
    snippet: str
    source: str = ""
    score: float = 0.0
    metadata: dict[str, object] = field(default_factory=dict)


def _terms(value: str) -> list[str]:
    """限制查询词数量，避免超长查询稀释单个候选的命中率。"""
    return query_terms(value)[:16]


def _matches(text: str, values: list[str]) -> int:
    """统计词列表中实际出现在文本里的词数量：表示每命中一个词贡献 1"""
    return sum(
        1 for value in values
        if value and value in text
    )


# 把 query 和 required 拆成词；
# 标题命中给二值分，普通词和必需词按命中比例给分，三项加权求和；
# 品牌/型号/类目任意命中就加对应权重；
# 如果全是泛词且没有任何具体业务词命中就扣分；
# 最后钳制到 0~1
def score_candidate(candidate: Candidate, query: str, required_terms: list[str] | None = None, *,
                    brand_terms: list[str] | None = None, model_terms: list[str] | None = None,
                    category_terms: list[str] | None = None, generic_terms: list[str] | None = None,
                    weights: dict[str, float] | None = None) -> float:
    """按标题、普通词、必需词及业务词加权计算候选相关性。"""
    weights = {**DEFAULT_WEIGHTS, **(weights or {})}
    # 允许调用方只覆盖部分权重，其余沿用默认配置。
    terms = _terms(query)
    required = [item.strip().lower() for item in (required_terms or []) if item.strip()]
    text = f"{candidate.title}\n{candidate.snippet}".lower()
    # 标题和正文合并用于命中统计，但标题另计更高区分度。
    title_score = 1.0 if any(
        term in candidate.title.lower()
        for term in terms
    ) else 0.0

    term_ratio = _matches(text, terms) / len(terms) if terms else 0.0

    required_ratio = _matches(text, required) / len(required) if required else 0.0

    score = weights["title_match"] * title_score + weights["term_match"] * term_ratio + weights[
        "required_match"] * required_ratio
    for key, values in (("brand_boost", brand_terms), ("model_boost", model_terms), ("category_boost", category_terms)):
        # 品牌、型号、类目命中提供业务侧加分。
        if values and any(item.strip().lower() in text for item in values if item.strip()):
            score += weights[key]
    generic = [item.strip().lower() for item in (generic_terms or []) if item.strip()]
    if generic and _matches(text, generic) == len(generic) and not any(item.strip().lower() in text for item in
                                                                       [*(brand_terms or []), *(model_terms or []),
                                                                        *(category_terms or [])] if item.strip()):
        # 只有全是泛词且没有具体业务词时才扣分。
        score -= weights["generic_penalty"]
    return max(0.0, min(1.0, score))


def rank_candidates(candidates: list[Candidate], query: str, limit: int = 5, min_score: float = 0.0,
                    **kwargs: object) -> list[Candidate]:
    """补充分数、稳定排序，并返回达到阈值的有限候选。"""
    for candidate in candidates:
        # 保留调用方已注入的非零分数，支持外部召回器提供评分。
        if candidate.score == 0:
            candidate.score = score_candidate(candidate, query, **kwargs)
    candidates.sort(key=lambda item: (-item.score, item.chunk_id))
    # chunk_id 是同分时的次关键字，保证结果顺序稳定可复现。
    return [item for item in candidates if item.score >= min_score][: max(1, min(limit, 50))]
