"""History command - List and display analysis records."""

import json
import sys
from datetime import datetime
from typing import Optional

import typer

from app.cli.client import APIClient, APIError
from app.cli.config import get_config
from app.cli.lib.state_manager import update_state

history_app = typer.Typer(help="Manage analysis history records")


def _format_timestamp(ts: str) -> str:
    """Parse ISO timestamp and format as readable date/time."""
    try:
        dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, AttributeError):
        return ts[:16] if ts else "Unknown"


def _format_score(label: str, score: int) -> str:
    """Format risk label with score."""
    if label == "可信":
        icon = "✅"
    elif label == "可疑":
        icon = "⚠️"
    elif label == "高风险":
        icon = "🔴"
    else:
        icon = "❓"
    return f"{icon} {label}({score})"


def _truncate_text(text: str, max_len: int = 60) -> str:
    """Truncate text with ellipsis."""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


@history_app.command("list")
def list_history(
    limit: int = typer.Option(
        10,
        "--limit",
        "-l",
        help="Number of records to show (1-100)",
        min=1,
        max=100,
    ),
) -> None:
    """List recent analysis records.
    
    Shows up to LIMIT recent analysis records with key information:
    - record_id: Unique identifier
    - time: Analysis timestamp
    - risk: Risk assessment label and score
    - preview: First 60 chars of analyzed text
    
    Example:
        truthcast history list
        truthcast history list --limit 20
    """
    config = get_config()
    client = APIClient(base_url=config.api_base, timeout=config.timeout, retry_times=config.retry_times)
    
    try:
        data = client.get(
            "/history",
            params={"limit": limit},
        )
        items = data.get("items", [])
        
        if not items:
            typer.echo("📭 暂无历史分析记录")
            return
        
        typer.echo(f"\n📋 历史分析记录 (最近{len(items)}条)\n")
        typer.echo(f"{'序号':<4} {'Record ID':<15} {'时间':<16} {'风险评估':<15} {'摘要'}")
        typer.echo("-" * 100)
        
        for idx, item in enumerate(items, 1):
            record_id = item.get("id", "")
            created_at = _format_timestamp(item.get("created_at", ""))
            risk_label = item.get("risk_label", "Unknown")
            risk_score = item.get("risk_score", 0)
            preview = _truncate_text(item.get("input_preview", ""))
            risk_str = f"{risk_label}({risk_score})"
            
            typer.echo(
                f"{idx:<4} {record_id:<15} {created_at:<16} {risk_str:<15} {preview}"
            )
        
        typer.echo()
        typer.echo("💡 提示: 使用 'truthcast history show <record_id>' 查看详情")
        typer.echo(f"        使用 'truthcast bind <record_id>' 绑定记录 ID\n")
        
    except APIError as e:
        typer.echo(f"\n{e.user_friendly_message()}", err=True)
        sys.exit(1)
    except Exception as e:
        typer.echo(f"\n❌ 未知错误: {e}", err=True)
        sys.exit(1)


@history_app.command("show")
def show_history(
    record_id: str = typer.Argument(..., help="Record ID to display"),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Output raw JSON instead of formatted text",
    ),
) -> None:
    """Display details of a specific analysis record.
    
    Shows comprehensive information including:
    - Basic metadata (ID, timestamp, risk assessment)
    - Analysis results (claims, evidence, report)
    - Simulation results (if available)
    - User feedback (if provided)
    
    Example:
        truthcast history show rec_abc123
        truthcast history show rec_abc123 --json
    """
    config = get_config()
    client = APIClient(base_url=config.api_base, timeout=config.timeout, retry_times=config.retry_times)
    
    try:
        data = client.get(
            f"/history/{record_id}",
        )
        
        if json_output or config.output_format == "json":
            # Output raw JSON
            typer.echo(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            # Format as human-readable text
            _print_history_detail(data)
    
    except APIError as e:
        if e.status_code == 404:
            typer.echo(
                f"\n❌ 记录不存在: {record_id}\n\n"
                f"请检查 record_id 是否正确，或使用 'truthcast history list' 查看所有记录。\n",
                err=True,
            )
        else:
            typer.echo(f"\n{e.user_friendly_message()}", err=True)
        sys.exit(1)
    except Exception as e:
        typer.echo(f"\n❌ 未知错误: {e}", err=True)
        sys.exit(1)


def _print_history_detail(data: dict) -> None:
    """Print history detail in human-readable format."""
    record_id = data.get("id", "N/A")
    created_at = _format_timestamp(data.get("created_at", ""))
    risk_label = data.get("risk_label", "Unknown")
    risk_score = data.get("risk_score", 0)
    scenario = data.get("detected_scenario", "Unknown")
    domains = data.get("evidence_domains", [])
    feedback = data.get("feedback_status", "未反馈")
    
    typer.echo(f"\n📊 分析记录详情\n")
    typer.echo(f"  Record ID:     {record_id}")
    typer.echo(f"  时间:         {created_at}")
    typer.echo(f"  风险评估:      {_format_score(risk_label, risk_score)}")
    typer.echo(f"  识别场景:      {scenario}")
    typer.echo(f"  证据域:        {', '.join(domains) if domains else '无'}")
    typer.echo(f"  用户反馈:      {feedback}")
    
    # Show input text (first 200 chars)
    input_text = data.get("input_text", "")
    if input_text:
        preview = _truncate_text(input_text, 200)
        typer.echo(f"\n  原始文本:")
        typer.echo(f"    {preview}")
    
    # Show claims if available
    report = data.get("report", {})
    if report:
        claims_reports = report.get("claim_reports", [])
        if claims_reports:
            typer.echo(f"\n  主张数量: {len(claims_reports)}")
            for idx, claim_report in enumerate(claims_reports[:5], 1):
                claim_text = claim_report.get("claim_text", "")
                stance = claim_report.get("final_stance", "")
                typer.echo(f"    {idx}. {_truncate_text(claim_text, 70)} [{stance}]")
            if len(claims_reports) > 5:
                typer.echo(f"    ... 还有 {len(claims_reports) - 5} 条主张")
        
        # Show conclusion
        conclusion = report.get("conclusion", "")
        if conclusion:
            typer.echo(f"\n  综合结论:")
            typer.echo(f"    {_truncate_text(conclusion, 150)}")
    
    # Show simulation if available
    simulation = data.get("simulation")
    if simulation:
        typer.echo(f"\n  舆情预演:")
        emotion = simulation.get("emotion_distribution", {})
        if emotion:
            top_emotion = max(emotion.items(), key=lambda x: x[1]) if emotion else ("无", 0)
            typer.echo(f"    主导情绪: {top_emotion[0]} ({top_emotion[1]:.0%})")
    
    typer.echo(f"\n💡 提示: 使用 --json 选项查看完整数据\n")


def history(
    action: str = typer.Argument(
        "list",
        help="Action: list, show",
    ),
    record_id: Optional[str] = typer.Argument(
        None,
        help="Record ID (required for show action)",
    ),
    limit: int = typer.Option(
        10,
        "--limit",
        "-l",
        help="Number of records to list (for list action)",
        min=1,
        max=100,
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Output JSON format",
    ),
) -> None:
    """Manage analysis history records.
    
    This command provides a simple interface to list and view historical analysis results.
    For more advanced usage, use subcommands: list, show
    
    Examples:
        truthcast history list
        truthcast history show rec_abc123
        truthcast history show rec_abc123 --json
    """
    # Route to appropriate subcommand
    if action == "list":
        list_history(limit=limit)
    elif action == "show":
        if not record_id:
            typer.echo("❌ 错误: 'show' 操作需要提供 record_id\n", err=True)
            typer.echo("用法: truthcast history show <record_id>", err=True)
            sys.exit(1)
        show_history(record_id=record_id, json_output=json_output)
    else:
        typer.echo(
            f"❌ 未知操作: {action}\n\n"
            f"支持的操作: list, show\n",
            err=True,
        )
        sys.exit(1)
