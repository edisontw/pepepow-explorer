from __future__ import annotations

import copy
from threading import RLock
from typing import Any

from monitor.cache.base import CacheBackend


class MemoryCache(CacheBackend):
    name = "memory"

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._lock = RLock()

    def get_json(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return copy.deepcopy(self._data.get(key, default))

    def set_json(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = copy.deepcopy(value)

    def append_json_list(self, key: str, value: Any, limit: int) -> list[Any]:
        with self._lock:
            current = list(self._data.get(key, []))
            current.append(copy.deepcopy(value))
            current = current[-limit:]
            self._data[key] = current
            return copy.deepcopy(current)

    def replace_json_list(self, key: str, values: list[Any]) -> list[Any]:
        with self._lock:
            self._data[key] = copy.deepcopy(values)
            return copy.deepcopy(values)

    def ping(self) -> None:
        return None
