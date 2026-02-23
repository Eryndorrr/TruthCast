"""
TruthCast CLI Main Entry Point

Provides command-line interface for fake news detection, opinion simulation,
and content generation.
"""

import sys
from pathlib import Path

import typer

# Load project environment variables immediately upon module import
from app.core.env_loader import load_project_env

# Initialize environment before any other imports that depend on it
load_project_env()

# Now safe to import the rest
from app.cli.commands import analyze, chat, content, export, history, simulate, state
from app.cli.config import get_config
from app.cli._globals import set_global_config, get_global_config

# Global configuration object (set by callback)



def config_callback(
    api_base: str = typer.Option(
        None,
        "--api-base",
        help="Backend API base URL (e.g., http://127.0.0.1:8000). Overrides TRUTHCAST_API_BASE env var.",
        envvar="TRUTHCAST_API_BASE",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Output results in JSON format instead of plain text.",
    ),
    timeout: int = typer.Option(
        None,
        "--timeout",
        help="Request timeout in seconds. Overrides TRUTHCAST_CLI_TIMEOUT env var.",
        envvar="TRUTHCAST_CLI_TIMEOUT",
    ),
) -> None:
    """Global options callback. Sets configuration for all commands."""
    output_format = "json" if json_output else None
    config = get_config(
        api_base=api_base,
        timeout=timeout,
        output_format=output_format,  # type: ignore
    )
    set_global_config(config)


app = typer.Typer(
    name="truthcast",
    help="TruthCast: Fake news detection + opinion simulation intelligent system",
    no_args_is_help=True,
    callback=config_callback,
)

# Register command groups
app.command()(chat.chat)
app.command()(analyze.analyze)
app.command()(simulate.simulate)
app.command()(history.history)
app.command()(content.content)
app.command()(export.export_cmd)
app.command()(state.state)







def main() -> None:
    """Main entry point for CLI."""
    try:
        app()
    except KeyboardInterrupt:
        print("\n[✓] Aborted by user.", file=sys.stderr)
        sys.exit(0)
    except Exception as e:
        print(f"\n[✗] Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
