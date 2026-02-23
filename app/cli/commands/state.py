"""State command - Pipeline state and record binding management."""

import sys
from typing import Optional

import typer

from app.cli.lib.state_manager import get_state_value, load_state, save_state, update_state

state_app = typer.Typer(help="Manage state and bound records")


@state_app.command("bind")
def bind_record(
    record_id: str = typer.Argument(..., help="Record ID to bind"),
) -> None:
    """Bind a record ID to local state for convenient access.
    
    Once bound, subsequent commands can use the bound record_id without
    explicitly specifying --record-id parameter.
    
    Example:
        truthcast bind rec_abc123
        truthcast show  # Uses bound rec_abc123
    """
    if not record_id or len(record_id) < 3:
        typer.echo("❌ 错误: record_id 应该至少包含 3 个字符\n", err=True)
        sys.exit(1)
    
    try:
        update_state("bound_record_id", record_id)
        typer.echo(f"\n✅ 已绑定 record_id: {record_id}\n")
        typer.echo(f"💡 提示: 后续命令可使用绑定的记录，无需重复指定 record_id\n")
    except Exception as e:
        typer.echo(f"\n❌ 绑定失败: {e}\n", err=True)
        sys.exit(1)


@state_app.command("show")
def show_state() -> None:
    """Show current local state."""
    state = load_state()
    
    if not state:
        typer.echo("\n📭 本地状态为空\n")
        return
    
    typer.echo("\n📋 本地状态:\n")
    for key, value in state.items():
        typer.echo(f"  {key}: {value}")
    typer.echo()


@state_app.command("clear")
def clear_state(
    confirm: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip confirmation and clear immediately",
    ),
) -> None:
    """Clear all local state."""
    if not confirm:
        typer.echo("⚠️  这将清除所有本地状态（包括绑定的 record_id）")
        response = typer.confirm("确实要继续吗?")
        if not response:
            typer.echo("✓ 已取消")
            return
    
    try:
        save_state({})
        typer.echo("\n✅ 已清除所有本地状态\n")
    except Exception as e:
        typer.echo(f"\n❌ 清除失败: {e}\n", err=True)
        sys.exit(1)


def state(
    action: str = typer.Argument(
        "show",
        help="Action: bind, show, clear",
    ),
    record_id: Optional[str] = typer.Argument(
        None,
        help="Record ID (required for bind action)",
    ),
) -> None:
    """Manage local state and record bindings.
    
    This command handles local state management, including:
    - bind: Bind a record_id for convenient access
    - show: Display current state
    - clear: Clear all state
    
    Examples:
        truthcast state bind rec_abc123
        truthcast state show
        truthcast state clear
    """
    if action == "bind":
        if not record_id:
            typer.echo("❌ 错误: 'bind' 操作需要提供 record_id\n", err=True)
            typer.echo("用法: truthcast state bind <record_id>", err=True)
            sys.exit(1)
        bind_record(record_id=record_id)
    elif action == "show":
        show_state()
    elif action == "clear":
        clear_state()
    else:
        typer.echo(
            f"❌ 未知操作: {action}\n\n"
            f"支持的操作: bind, show, clear\n",
            err=True,
        )
        sys.exit(1)
