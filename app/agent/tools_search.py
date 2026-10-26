from __future__ import annotations

 

from app.agent.tools_support import *  # noqa: F401,F403


# 能力混入类，把这一领域的操作组合到主类中。
class ToolRegistrySearchMixin:
    @staticmethod
    def normalize_search_query(query: str) -> str:
        text = query.strip()
        for keyword in ('帮我', '请问', '推荐', '推荐一下', '怎么选', '怎么挑', '有什么', '适合我'):
            text = text.replace(keyword, ' ')
        for category in ('手机', '电脑', '鼠标', '耳机', '跑鞋', '面霜', '精华', '相机'):
            if category in query:
                return category
        return re.sub('\\s+', ' ', text).strip() or query.strip()

    @staticmethod
    def _argument_values(arguments: dict[str, object] | None, key: str) -> list[str]:
        raw = (arguments or {}).get(key, [])
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, list):
            return []
        return [str(item).strip().lower() for item in raw if str(item).strip()]

    @staticmethod
    def _product_text(product: Product, merchant: Merchant) -> str:
        category_label = CATEGORY_LABELS.get(product.category_id, '')
        return ' '.join([product.product_id, product.name, product.brand, product.category_id, category_label, merchant.name, product.stock_status, *(product.tags_json or []), *(product.selling_points_json or []), product.recommend_reason, *(product.risk_notes_json or [])]).lower()

    async def search_products(self, query: str, limit: int=5, arguments: dict[str, object] | None=None) -> ToolResult:
        normalized = self.normalize_search_query(query)
        limit = max(1, min(limit, 20))
        constraints = arguments.get('constraints', {}) if isinstance(arguments, dict) else {}
        negative = arguments.get('negative', {}) if isinstance(arguments, dict) else {}
        constraints = constraints if isinstance(constraints, dict) else {}
        negative = negative if isinstance(negative, dict) else {}
        positive_terms = self._argument_values(constraints, 'terms') + self._argument_values(constraints, 'brands') + self._argument_values(constraints, 'categories')
        negative_terms = self._argument_values(negative, 'terms') + self._argument_values(negative, 'brands') + self._argument_values(negative, 'categories')
        rows, _total = await self.repository.list_product_records(normalized, '', 1, max(10, min(80, limit * 8)))
        candidate_ids = [product.product_id for product, _merchant, _sku in rows]
        filtered_rows = []
        dropped_ids: list[str] = []
        for product, merchant, sku in rows:
            text = self._product_text(product, merchant)
            if negative_terms and any((term in text for term in negative_terms)):
                dropped_ids.append(product.product_id)
                continue
            if positive_terms and (not all((term in text for term in positive_terms))):
                continue
            price = Decimal(str(getattr(sku, 'price', None) or product.price))
            price_filter = constraints.get('price') if isinstance(constraints.get('price'), dict) else {}
            try:
                minimum = Decimal(str(price_filter.get('min'))) if price_filter.get('min') is not None else None
                maximum = Decimal(str(price_filter.get('max'))) if price_filter.get('max') is not None else None
            except (ArithmeticError, TypeError, ValueError):
                minimum = maximum = None
            if minimum is not None and price < minimum:
                dropped_ids.append(product.product_id)
                continue
            if maximum is not None and price > maximum:
                dropped_ids.append(product.product_id)
                continue
            filtered_rows.append((product, merchant, sku))
        if not filtered_rows and rows and negative_terms:
            return ToolResult(tool='search_products', ok=True, message='召回候选全部命中否定条件', result={'query': normalized, 'items': [], 'candidate_product_ids': candidate_ids, 'dropped_product_ids': dropped_ids, 'relevance_status': 'weak', 'relevance_reason': '候选商品全部命中用户否定约束', 'rerank': {'enabled': False}})
        rerank_scores: list[dict[str, object]] = []
        rerank_enabled = bool(self.settings and getattr(self.settings, 'product_rerank_enabled', True))
        rerank_provider = 'rule'
        rerank_error = ''
        ordered = list(filtered_rows)
        if ordered:

            def rule_score(row) -> tuple[float, int, list[str]]:
                product, merchant, _sku = row
                text = self._product_text(product, merchant)
                score = 0.0
                reasons: list[str] = []
                terms = [term for term in re.split('\\s+', normalized.lower()) if term]
                for term in terms:
                    if term in text:
                        score += 6.0
                        reasons.append(f'query_term:{term}')
                    if term in product.name.lower():
                        score += 3.0
                for term in positive_terms:
                    if term in text:
                        score += 12.0
                        reasons.append(f'constraint:{term}')
                    if term in product.brand.lower():
                        score += 18.0
                if normalized.lower() in text:
                    score += 2.0
                return (score, len(reasons), reasons)
            scored = [(rule_score(row), index, row) for index, row in enumerate(ordered)]
            scored.sort(key=lambda item: (-item[0][0], -item[0][1], item[1]))
            ordered = [item[2] for item in scored]
            rerank_scores = [{'product_id': row[2][0].product_id, 'score': round(row[0][0], 6), 'reasons': row[0][2], 'index': index} for index, row in enumerate(scored)]
            rerank_key = getattr(self.settings, 'product_rerank_api_key', '') if self.settings is not None else ''
            if rerank_enabled and self.settings is not None and getattr(self.settings, 'product_rerank_model_enabled', True) and rerank_key:
                try:
                    max_candidates = max(1, min(int(getattr(self.settings, 'product_rerank_max_candidates', 80)), len(ordered)))
                    candidates = ordered[:max_candidates]
                    documents = [self._product_text(product, merchant) for product, merchant, _sku in candidates]
                    results = await ProductReranker(getattr(self.settings, 'product_rerank_base_url', 'https://dashscope.aliyuncs.com'), rerank_key, getattr(self.settings, 'product_rerank_model', 'qwen3-vl-rerank'), float(getattr(self.settings, 'ai_timeout_seconds', 20.0))).rerank(query, documents, max_candidates)
                    rerank_provider = 'dashscope'
                    ordered = [candidates[item.index] for item in results] + [row for row in ordered if row not in candidates]
                    rerank_scores = [{'product_id': candidates[item.index][0].product_id, 'score': item.score, 'reasons': ['qwen3_vl_rerank'], 'index': index} for index, item in enumerate(results)]
                    top_score = rerank_scores[0]['score'] if rerank_scores else 0.0
                    threshold = max(float(getattr(self.settings, 'product_rerank_min_score', 0.5)), top_score - float(getattr(self.settings, 'product_rerank_max_score_delta', 0.12)))
                    ordered = [row for row in ordered if any((score['product_id'] == row[0].product_id and float(score['score']) >= threshold for score in rerank_scores)) or row not in candidates]
                except (RerankUnavailable, OSError, ValueError) as error:
                    rerank_error = type(error).__name__
                    if not getattr(self.settings, 'product_rerank_fallback_rule_enabled', True):
                        ordered = []
        ordered = ordered[:limit]
        product_ids = [product.product_id for product, _merchant, _sku in ordered]
        items = [product_payload(product, merchant, sku) for product, merchant, sku in ordered]
        relevance_status = 'ok' if items else 'weak' if candidate_ids else 'no_match'
        return ToolResult(tool='search_products', ok=True, message='' if items else '当前商品库没有找到匹配商品', product_ids=product_ids, result={'query': normalized, 'items': items, 'candidate_product_ids': candidate_ids, 'dropped_product_ids': dropped_ids, 'relevance_status': relevance_status, 'relevance_reason': '' if items else '没有达到可推荐相关性要求', 'constraints': constraints, 'negative': negative, 'rerank': {'enabled': rerank_enabled, 'provider': rerank_provider, 'error': rerank_error, 'scores': rerank_scores}})

    async def search_knowledge(self, query: str, limit: int=5) -> ToolResult:
        retrieval = await RAGService(self.repository, build_vector_provider(self.settings) if self.settings is not None else None).search_knowledge(query, limit)
        chunks = retrieval.candidates
        chunk_ids = [chunk.chunk_id for chunk in chunks]
        blocks = [{'type': 'citation', 'citation': {'chunkId': chunk.chunk_id, 'title': chunk.title, 'snippet': chunk.snippet, 'source': chunk.source, 'score': round(chunk.score, 6)}} for chunk in chunks]
        return ToolResult(tool='search_knowledge', ok=bool(chunks), message='' if chunks else '当前资料库没有找到匹配内容', chunk_ids=chunk_ids, blocks=blocks, result={'items': blocks, 'trace': retrieval.trace})

    async def search_image_products(self, account_id: str, settings: Settings, attachments: list[dict[str, object]], limit: int=5) -> ToolResult:
        attachment = next((item for item in attachments if str(item.get('type', 'image')).lower() == 'image'), None)
        if attachment is None:
            return ToolResult(tool='search_image_products', ok=False, message='请先上传一张商品图片')
        service = ImageSearchService(self.repository, settings, build_object_store(settings), build_image_embedder(settings), account_id=account_id)
        try:
            result = await service.search(file_id=str(attachment.get('file_id') or ''), object_key=str(attachment.get('object_key') or ''), image_url=str(attachment.get('url') or attachment.get('image_url') or ''), top_k=limit)
        except (ImageEmbeddingError, FileNotFoundError, OSError) as error:
            return ToolResult(tool='search_image_products', ok=False, message='当前图片检索能力不可用，请改用文字描述或稍后重试。', result={'error': type(error).__name__})
        items = list(result.get('items', []))
        product_ids = [str(item.get('productId')) for item in items if item.get('productId')]
        blocks = [{'type': 'product_refs', 'product_ids': product_ids}] if product_ids else [{'type': 'warning', 'code': str(result.get('match_status', 'no_match')), 'message': '当前图片没有找到可验证的相似商品。'}]
        return ToolResult(tool='search_image_products', ok=bool(items), message='' if items else '当前图片没有找到可验证的相似商品', product_ids=product_ids, blocks=blocks, result=result)
