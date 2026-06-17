from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class CacheBackend(ABC):
    name: str

    @abstractmethod
    def get_json(self, key: str, default: Any = None) -> Any:
        raise NotImplementedError

    @abstractmethod
    def set_json(self, key: str, value: Any) -> None:
        raise NotImplementedError

    @abstractmethod
    def append_json_list(self, key: str, value: Any, limit: int) -> list[Any]:
        raise NotImplementedError

    @abstractmethod
    def replace_json_list(self, key: str, values: list[Any]) -> list[Any]:
        raise NotImplementedError

    @abstractmethod
    def ping(self) -> None:
        raise NotImplementedError
