from __future__ import annotations


import hashlib
import json
import secrets
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import String, and_, case, cast, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

# 数据访问模块：把业务查询封装为异步 Repository 操作。

from app.domain.models import (
    Account, AgentRun, AgentTraceEvent, AgentPrompt, AgentPromptPublishRecord,
    AppConfig, AuthToken, CartItem, Category, ChatSession, KnowledgeChunk,
    KnowledgeDocument, Coupon, Merchant, Order, OrderItem, Payment, Product,
    ProductImageVector, ProductSKU, ProductReview, PromotionRule, UserCoupon,
    UserMessage, StoredFile,
)
from app.security.auth import token_digest
from app.domain.status import can_transition
