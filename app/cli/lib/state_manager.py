"""
Local state management for CLI.

Stores last record_id, session_id, and API base for convenience.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional


def _get_state_file_path() -> Path:
    """
    Get the state file path based on OS.
    
    Returns:
        Path to state.json file
    """
    if os.name == "nt":  # Windows
        # Use APPDATA on Windows
        app_data = os.getenv("APPDATA")
        if app_data:
            state_dir = Path(app_data) / "truthcast"
        else:
            # Fallback to user home
            state_dir = Path.home() / ".truthcast"
    else:  # Linux/macOS
        state_dir = Path.home() / ".truthcast"
    
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / "state.json"


def load_state() -> Dict[str, Any]:
    """
    Load state from local file.
    
    Returns:
        State dictionary (empty if file doesn't exist)
    """
    state_file = _get_state_file_path()
    
    if not state_file.exists():
        return {}
    
    try:
        with open(state_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        # If corrupted, return empty state
        return {}


def save_state(state: Dict[str, Any]) -> None:
    """
    Save state to local file.
    
    Args:
        state: State dictionary to save
    """
    state_file = _get_state_file_path()
    
    try:
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
    except IOError:
        # Silently fail if cannot write
        pass


def update_state(key: str, value: Any) -> None:
    """
    Update a single key in state.
    
    Args:
        key: State key to update
        value: Value to set
    """
    state = load_state()
    state[key] = value
    save_state(state)


def get_state_value(key: str, default: Any = None) -> Any:
    """
    Get a single value from state.
    
    Args:
        key: State key to retrieve
        default: Default value if key doesn't exist
        
    Returns:
        Value from state or default
    """
    state = load_state()
    return state.get(key, default)


def clear_state() -> None:
    """Clear all state."""
    save_state({})
