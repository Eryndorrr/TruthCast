"""
Global state for CLI (avoids circular imports).

This module holds the global CLI configuration that is set by the main callback
and accessed by individual command modules.
"""

from app.cli.config import CLIConfig

# Global configuration object (set by main callback)
_global_config: CLIConfig = CLIConfig()


def set_global_config(config: CLIConfig) -> None:
    """Set the global CLI configuration."""
    global _global_config
    _global_config = config


def get_global_config() -> CLIConfig:
    """Get the current global CLI configuration."""
    return _global_config
