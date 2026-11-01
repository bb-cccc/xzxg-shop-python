from __future__ import annotations



import logging
import time
from collections import defaultdict

try:
    from redis.exceptions import RedisError
except ImportError:  # pragma: no cover —— 本地测试中 Redis 是可选依赖

    class RedisError(Exception):
        pass



class RateLimiter:
    def __init__(self, settings, logger: logging.Logger | None = None) -> None:
        self.limit = max(1, int(settings.rate_limit_per_minute))
        self.logger = logger or logging.getLogger("xzxg.rate_limit")
        self.counts: defaultdict[str, tuple[int, float]] = defaultdict(lambda: (0, time.monotonic()))
        self.redis_client = None
        if settings.redis_url.strip():
            try:
                from redis.asyncio import Redis
                self.redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
            except ImportError:
                self.logger.warning("redis dependency unavailable; using process rate limiter")

    async def allow(self, key: str) -> bool:
        if self.redis_client is not None:
            try:
                bucket = f"xzxg:rate:{key}:{int(time.time() // 60)}"
                value = int(await self.redis_client.incr(bucket))
                if value == 1:
                    await self.redis_client.expire(bucket, 60)
                return value <= self.limit
            except (RedisError, OSError, TimeoutError):
                self.logger.warning("redis rate limiter unavailable; using process fallback", exc_info=True)
        count, started = self.counts[key]
        now = time.monotonic()
        if now - started >= 60:
            count, started = 0, now
        if count >= self.limit:
            return False
        self.counts[key] = (count + 1, started)
        return True

    async def close(self) -> None:
        if self.redis_client is not None:
            await self.redis_client.aclose()
