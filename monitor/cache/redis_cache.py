from __future__ import annotations

import json
from typing import Any

from monitor.cache.base import CacheBackend

try:  # pragma: no cover - dependency may be missing in local runtime
    import redis
except ImportError:  # pragma: no cover - dependency may be missing in local runtime
    redis = None


class RedisCache(CacheBackend):
    name = "redis"

    def __init__(self, url: str) -> None:
        if redis is None:  # pragma: no cover - dependency may be missing in local runtime
            raise RuntimeError("redis package is not installed")
        self._client = redis.Redis.from_url(url, decode_responses=True)

    def get_json(self, key: str, default: Any = None) -> Any:
        value = self._client.get(key)
        if value is None:
            return default
        return json.loads(value)

    def set_json(self, key: str, value: Any) -> None:
        self._client.set(key, json.dumps(value))

    def append_json_list(self, key: str, value: Any, limit: int) -> list[Any]:
        pipeline = self._client.pipeline()
        pipeline.rpush(key, json.dumps(value))
        pipeline.ltrim(key, -limit, -1)
        pipeline.lrange(key, 0, -1)
        _, _, values = pipeline.execute()
        return [json.loads(item) for item in values]

    def replace_json_list(self, key: str, values: list[Any]) -> list[Any]:
        pipeline = self._client.pipeline()
        pipeline.delete(key)
        if values:
            pipeline.rpush(key, *[json.dumps(item) for item in values])
        pipeline.execute()
        return values

    def ping(self) -> None:
        self._client.ping()
