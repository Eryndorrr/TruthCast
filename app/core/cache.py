"""
app/core/cache.py
-----------------
轻量级内存缓存（TTLCache），用于缓存高成本 LLM 调用结果。
键由输入文本的 SHA-256 哈希构成，避免存储原始文本。

环境变量：
  TRUTHCAST_CACHE_DETECT_TTL   风险快照缓存 TTL（秒，默认 300）
  TRUTHCAST_CACHE_CLAIMS_TTL   主张抽取缓存 TTL（秒，默认 300）
  TRUTHCAST_CACHE_MAX_SIZE     最大缓存条目数（默认 100）
"""
from __future__ import annotations

import hashlib
import os
import time
from threading import Lock
from typing import Any

from app.core.logger import get_logger

logger = get_logger("truthcast.cache")


def _int_env(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, default))
    except (ValueError, TypeError):
        return default


class TTLCache:
    """简单线程安全 TTL 内存缓存（不依赖第三方库）"""

    def __init__(self, maxsize: int, ttl: int) -> None:
        self._maxsize = maxsize
        self._ttl = ttl
        self._store: dict[str, tuple[Any, float]] = {}  # key -> (value, expire_at)
        self._lock = Lock()

    def _text_key(self, text: str) -> str:
        # 仅做首尾空白归一，不做 lower()——中文无大小写，英文大小写可能语义不同
        return hashlib.sha256(text.strip().encode()).hexdigest()

    def get(self, text: str) -> Any | None:
        key = self._text_key(text)
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expire_at = entry
            if time.monotonic() > expire_at:
                del self._store[key]
                return None
            return value

    def set(self, text: str, value: Any) -> None:
        key = self._text_key(text)
        expire_at = time.monotonic() + self._ttl
        with self._lock:
            # 超出 maxsize 时先清除已过期条目，再按最早过期时间淘汰
            if len(self._store) >= self._maxsize and key not in self._store:
                now = time.monotonic()
                # 先尝试清除所有已过期条目
                expired_keys = [k for k, (_, exp) in self._store.items() if exp <= now]
                for k in expired_keys:
                    del self._store[k]
                # 若仍超出则淘汰最早过期的条目（近似 LRU）
                if len(self._store) >= self._maxsize:
                    lru_key = min(self._store, key=lambda k: self._store[k][1])
                    del self._store[lru_key]
            self._store[key] = (value, expire_at)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    @property
    def ttl(self) -> int:
        return self._ttl

    def __len__(self) -> int:
        return len(self._store)


# ---- 全局缓存实例 ----
_maxsize = _int_env("TRUTHCAST_CACHE_MAX_SIZE", 100)

detect_cache = TTLCache(
    maxsize=_maxsize,
    ttl=_int_env("TRUTHCAST_CACHE_DETECT_TTL", 300),
)

claims_cache = TTLCache(
    maxsize=_maxsize,
    ttl=_int_env("TRUTHCAST_CACHE_CLAIMS_TTL", 300),
)

logger.info(
    "缓存已初始化：maxsize=%d, detect_ttl=%ds, claims_ttl=%ds",
    _maxsize,
    detect_cache.ttl,
    claims_cache.ttl,
)
