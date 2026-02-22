"""
app/core/concurrency.py
-----------------------
全局 LLM 并发限流（基于 threading.Semaphore）。

同一时刻允许并发进行的 LLM 调用数受 Semaphore 控制，超过等待队列时间则
抛出 429 Too Busy，避免对下游 LLM API 造成突发大量请求。

所有路由为同步 def，故使用 threading.Semaphore 而非 asyncio.Semaphore。

环境变量：
  TRUTHCAST_LLM_CONCURRENCY       最大并发 LLM 调用数（默认 5）
  TRUTHCAST_MAX_QUEUE_WAIT_SEC    最大等待秒数（默认 30）
"""
from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from typing import Generator

from fastapi import HTTPException

from app.core.logger import get_logger

logger = get_logger("truthcast.concurrency")


def _int_env(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, default))
    except (ValueError, TypeError):
        return default


_concurrency = _int_env("TRUTHCAST_LLM_CONCURRENCY", 5)
_max_wait = _int_env("TRUTHCAST_MAX_QUEUE_WAIT_SEC", 30)

# 全局信号量；由 init_semaphore() 在 FastAPI lifespan 启动时设置。
# 注意：单元测试若不走 lifespan，请在 fixture 中 mock 该变量或直接调用 init_semaphore()，
# 避免不同测试复用同一计数器导致状态泄露。
_semaphore: threading.Semaphore | None = None


def init_semaphore() -> None:
    """在 FastAPI lifespan 启动时初始化 Semaphore"""
    global _semaphore
    _semaphore = threading.Semaphore(_concurrency)
    logger.info("并发限流已初始化：max_concurrency=%d, max_wait=%ds", _concurrency, _max_wait)


def _get_semaphore() -> threading.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = threading.Semaphore(_concurrency)
    return _semaphore


@contextmanager
def llm_slot() -> Generator[None, None, None]:
    """
    同步上下文管理器，限制同时持有的 LLM 调用槽位。
    超时视为请求过载，抛出 HTTP 429。
    """
    sem = _get_semaphore()
    acquired = sem.acquire(timeout=_max_wait)
    if not acquired:
        logger.warning("LLM 并发等待超时（%ds），返回 429", _max_wait)
        raise HTTPException(status_code=429, detail="服务繁忙，等待超时，请稍后重试")
    try:
        yield
    finally:
        sem.release()
