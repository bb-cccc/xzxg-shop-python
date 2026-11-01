from __future__ import annotations



from typing import Any


def _bool(value: str, fallback: bool) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"} if value.strip() else fallback


def _loopback_url(value: str) -> bool:
    normalized = value.strip().lower()
    return normalized.startswith("http://127.0.0.1") or normalized.startswith("http://localhost")


def apply_database_config(settings, values: dict[str, str]):
    """Apply runtime settings without mixing text and image model providers.

    Provider-neutral ``ai.*`` entries are explicit runtime overrides. Legacy
    ``ai.qwen.*`` entries only supply a complete fallback configuration when
    neither the environment nor the neutral entries configure a text model.
    """
    update: dict[str, Any] = {}
    text_fields = {
        "base_url": "ai_base_url",
        "api_key": "ai_api_key",
        "small_model": "ai_small_model",
        "large_model": "ai_large_model",
    }
    has_text_settings = any(str(getattr(settings, attr, "")).strip() for attr in text_fields.values())
    has_neutral_settings = any(values.get(f"ai.{name}", "").strip() for name in text_fields)
    text_prefix = "ai" if has_neutral_settings else ("ai.qwen" if not has_text_settings else "")
    if text_prefix:
        for name, attr in text_fields.items():
            value = values.get(f"{text_prefix}.{name}", "").strip()
            if value:
                update[attr] = value

    direct = {
        "image_embedding.provider": "image_embedding_provider", "image_embedding.base_url": "image_embedding_base_url", "image_embedding.api_key": "image_embedding_api_key", "image_embedding.model": "image_embedding_model",
        "milvus.address": "milvus_address", "milvus.token": "milvus_token", "embedding.base_url": "embedding_base_url", "embedding.api_key": "embedding_api_key", "embedding.model": "embedding_model", "embedding.provider": "embedding_provider",
        "files.storage_provider": "file_storage_provider", "files.local_dir": "file_storage_local_dir",
        "retrieval.product.rerank.base_url": "product_rerank_base_url", "retrieval.product.rerank.api_key": "product_rerank_api_key", "retrieval.product.rerank.model": "product_rerank_model",
    }
    for key, attr in direct.items():
        if values.get(key, "").strip():
            if key == "milvus.address" and _loopback_url(values[key]) and not _loopback_url(str(getattr(settings, attr, ""))):
                continue
            if key == "embedding.provider" and str(getattr(settings, attr, "")).lower() == "local_hash" and values[key].strip().lower() == "dashscope":
                continue
            if key == "image_embedding.provider" and str(getattr(settings, attr, "")).lower() in {"local", "local_histogram", "histogram"} and values[key].strip().lower() == "dashscope":
                continue
            update[attr] = values[key].strip()
    if "ai.enabled" in values:
        if not (settings.ai_enabled and not _bool(values["ai.enabled"], settings.ai_enabled)):
            update["ai_enabled"] = _bool(values["ai.enabled"], settings.ai_enabled)
    if "vector.enabled" in values:
        if not (settings.rag_vector_enabled and not _bool(values["vector.enabled"], settings.rag_vector_enabled)):
            update["rag_vector_enabled"] = _bool(values["vector.enabled"], settings.rag_vector_enabled)
    if "image_embedding.dimension" in values:
        try:
            if not (str(getattr(settings, "image_embedding_provider", "")).lower() in {"local", "local_histogram", "histogram"} and int(values["image_embedding.dimension"]) == 1536):
                update["image_embedding_dimension"] = int(values["image_embedding.dimension"])
        except ValueError:
            pass
    if "embedding.dimension" in values:
        try:
            update["embedding_dimension"] = int(values["embedding.dimension"])
        except ValueError:
            pass
    for key, attr in (("retrieval.product.rerank.enabled", "product_rerank_enabled"), ("retrieval.product.rerank.model_enabled", "product_rerank_model_enabled"), ("retrieval.product.rerank.fallback_rule_enabled", "product_rerank_fallback_rule_enabled")):
        if key in values:
            update[attr] = _bool(values[key], bool(getattr(settings, attr)))
    for key, attr in (("retrieval.product.rerank.max_candidates", "product_rerank_max_candidates"),):
        if key in values:
            try:
                update[attr] = int(values[key])
            except ValueError:
                pass
    for key, attr in (("retrieval.product.rerank.model_min_score", "product_rerank_min_score"), ("retrieval.product.rerank.model_max_score_delta", "product_rerank_max_score_delta")):
        if key in values:
            try:
                update[attr] = float(values[key])
            except ValueError:
                pass

    # 本地直方图嵌入固定产生 64 维。即使过期的远端配置写着 512/1536，也要让运行时元数据保持一致。
    effective_provider = str(update.get("image_embedding_provider", getattr(settings, "image_embedding_provider", ""))).lower()
    if effective_provider in {"local", "local_histogram", "histogram"}:
        update["image_embedding_dimension"] = 64
    return settings.model_copy(update=update)
