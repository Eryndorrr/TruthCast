"""
TruthCast CLI Configuration Module

Handles configuration priority:
  1. CLI flags (highest priority)
  2. Environment variables
  3. Default values (lowest priority)

Configuration sources:
  - API_BASE: TRUTHCAST_API_BASE or NEXT_PUBLIC_API_BASE (env) → http://127.0.0.1:8000 (default)
  - TIMEOUT: TRUTHCAST_CLI_TIMEOUT (env) → 30 (default, seconds)
  - OUTPUT_FORMAT: TRUTHCAST_CLI_OUTPUT_FORMAT (env) → text (default, text|json)
  - RETRY_TIMES: TRUTHCAST_CLI_RETRY_TIMES (env) → 3 (default)
"""

import os
from dataclasses import dataclass
from typing import Literal, Optional


@dataclass
class CLIConfig:
    """CLI Configuration object."""

    api_base: str = "http://127.0.0.1:8000"
    timeout: int = 30  # seconds
    output_format: Literal["text", "json"] = "text"
    retry_times: int = 3

    def to_dict(self) -> dict:
        """Convert to dictionary (safe for display, no secrets)."""
        return {
            "api_base": self.api_base,
            "timeout": self.timeout,
            "output_format": self.output_format,
            "retry_times": self.retry_times,
        }


def get_api_base_from_env() -> str:
    """
    Get API base URL from environment variables.
    
    Priority:
      1. TRUTHCAST_API_BASE
      2. NEXT_PUBLIC_API_BASE
      3. Default: http://127.0.0.1:8000
    """
    api_base = os.getenv("TRUTHCAST_API_BASE")
    if api_base:
        return api_base

    api_base = os.getenv("NEXT_PUBLIC_API_BASE")
    if api_base:
        return api_base

    return "http://127.0.0.1:8000"


def get_timeout_from_env() -> int:
    """
    Get timeout value from environment variables.
    
    Source: TRUTHCAST_CLI_TIMEOUT (seconds)
    Default: 30
    """
    try:
        timeout = os.getenv("TRUTHCAST_CLI_TIMEOUT")
        if timeout:
            return int(timeout)
    except (ValueError, TypeError):
        pass

    return 30


def get_output_format_from_env() -> Literal["text", "json"]:
    """
    Get output format from environment variables.
    
    Source: TRUTHCAST_CLI_OUTPUT_FORMAT (text|json)
    Default: text
    """
    output_format = os.getenv("TRUTHCAST_CLI_OUTPUT_FORMAT", "text").lower()
    if output_format in ("text", "json"):
        return output_format  # type: ignore
    return "text"


def get_retry_times_from_env() -> int:
    """
    Get retry times from environment variables.
    
    Source: TRUTHCAST_CLI_RETRY_TIMES
    Default: 3
    """
    try:
        retry_times = os.getenv("TRUTHCAST_CLI_RETRY_TIMES")
        if retry_times:
            return int(retry_times)
    except (ValueError, TypeError):
        pass

    return 3


def get_config(
    api_base: Optional[str] = None,
    timeout: Optional[int] = None,
    output_format: Optional[Literal["text", "json"]] = None,
    retry_times: Optional[int] = None,
) -> CLIConfig:
    """
    Build CLI configuration with priority: CLI flag > env > default.

    Args:
        api_base: CLI flag override for API base URL
        timeout: CLI flag override for timeout (seconds)
        output_format: CLI flag override for output format (text|json)
        retry_times: CLI flag override for retry times

    Returns:
        CLIConfig object with resolved values
    """
    return CLIConfig(
        api_base=api_base or get_api_base_from_env(),
        timeout=timeout or get_timeout_from_env(),
        output_format=output_format or get_output_format_from_env(),
        retry_times=retry_times or get_retry_times_from_env(),
    )
