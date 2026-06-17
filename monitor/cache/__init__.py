from __future__ import annotations

import logging

from monitor.cache.base import CacheBackend
from monitor.cache.memory import MemoryCache
from monitor.cache.redis_cache import RedisCache
from monitor.config import Settings


def build_cache(settings: Settings, logger: logging.Logger) -> CacheBackend:
    if settings.redis_url:
        try:
            cache = RedisCache(settings.redis_url)
            cache.ping()
            logger.info("monitor cache backend ready: redis")
            return cache
        except Exception as exc:  # pragma: no cover - depends on host runtime
            logger.warning("redis unavailable, falling back to memory cache: %s", exc)

    logger.info("monitor cache backend ready: memory")
    return MemoryCache()
