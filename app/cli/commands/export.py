"""Export command - Export analysis results."""

import json
import sys
from pathlib import Path
from typing import Any, Optional

import typer

from app.cli._globals import get_global_config
from app.cli.client import APIClient, APIError
from app.cli.lib.state_manager import get_state_value, update_state


def _default_export_dir() -> Path:
    base = Path.home() / ".truthcast" / "exports"
    base.mkdir(parents=True, exist_ok=True)
    return base


# Detect if console supports unicode/emoji
def _supports_unicode() -> bool:
    """Check if console supports unicode output."""
    try:
        # Try encoding a test emoji
        "\u2705".encode(sys.stdout.encoding or 'utf-8')
        return True
    except (UnicodeEncodeError, LookupError):
        return False


_UNICODE_SUPPORT = _supports_unicode()


def _emoji(unicode_char: str, ascii_fallback: str) -> str:
    """Return emoji if supported, otherwise ASCII fallback."""
    return unicode_char if _UNICODE_SUPPORT else ascii_fallback


def _to_markdown(history_detail: dict[str, Any]) -> str:
    record_id = history_detail.get("id", "")
    created_at = history_detail.get("created_at", "")
    risk_label = history_detail.get("risk_label", "")
    risk_score = history_detail.get("risk_score", "")

    lines: list[str] = []
    lines.append(f"# TruthCast Export ({record_id})")
    if created_at:
        lines.append(f"\nCreated at: {created_at}")
    if risk_label or risk_score != "":
        lines.append(f"\nRisk: {risk_label} ({risk_score})")

    input_text = history_detail.get("input_text") or ""
    if input_text:
        lines.append("\n## Input")
        lines.append("\n```text")
        lines.append(str(input_text).rstrip())
        lines.append("```")

    report = history_detail.get("report") or {}
    if report:
        lines.append("\n## Report")
        conclusion = report.get("conclusion") or ""
        if conclusion:
            lines.append("\n### Conclusion")
            lines.append(f"\n{conclusion}")

        summary = report.get("summary") or report.get("tldr") or ""
        if summary:
            lines.append("\n### TL;DR")
            lines.append(f"\n{summary}")

        claim_reports = report.get("claim_reports") or []
        if isinstance(claim_reports, list) and claim_reports:
            lines.append("\n### Claims")
            for idx, cr in enumerate(claim_reports, 1):
                if not isinstance(cr, dict):
                    continue
                claim_text = cr.get("claim_text") or cr.get("text") or ""
                stance = cr.get("final_stance") or cr.get("stance") or ""
                confidence = cr.get("final_confidence") or cr.get("confidence") or ""
                header = f"{idx}. {claim_text}" if claim_text else f"{idx}. (claim)"
                lines.append(f"\n- {header}")
                if stance or confidence != "":
                    lines.append(f"  - stance: {stance}  confidence: {confidence}")

    evidences = history_detail.get("evidences") or []
    if isinstance(evidences, list) and evidences:
        lines.append("\n## Evidence")
        max_items = 20
        for idx, ev in enumerate(evidences[:max_items], 1):
            if not isinstance(ev, dict):
                continue
            title = ev.get("title") or ev.get("source") or "(evidence)"
            url = ev.get("url") or ""
            stance = ev.get("stance") or ""
            lines.append(f"\n- {idx}. {title}")
            if url:
                lines.append(f"  - url: {url}")
            if stance:
                lines.append(f"  - stance: {stance}")
        if len(evidences) > max_items:
            lines.append(f"\n(… truncated, total evidences: {len(evidences)})")

    simulation = history_detail.get("simulation")
    if isinstance(simulation, dict) and simulation:
        lines.append("\n## Simulation")
        suggestion = simulation.get("suggestion") or {}
        if isinstance(suggestion, dict) and suggestion.get("summary"):
            lines.append("\n### Suggestion Summary")
            lines.append(f"\n{suggestion.get('summary')}")

    content = history_detail.get("content")
    if isinstance(content, dict) and content:
        lines.append("\n## Content")
        clar = content.get("clarification")
        if isinstance(clar, dict) and (clar.get("short") or clar.get("medium") or clar.get("long")):
            lines.append("\n### Clarification")
            if clar.get("short"):
                lines.append("\n#### Short")
                lines.append(f"\n{clar.get('short')}")
            if clar.get("medium"):
                lines.append("\n#### Medium")
                lines.append(f"\n{clar.get('medium')}")
            if clar.get("long"):
                lines.append("\n#### Long")
                lines.append(f"\n{clar.get('long')}")

    lines.append("")
    return "\n".join(lines)


def export_cmd(
    record_id: Optional[str] = typer.Option(
        None,
        "--record",
        "--record-id",
        "-r",
        help="Record ID to export (defaults to bound_record_id)",
    ),
    format_type: str = typer.Option(
        "markdown",
        "--format",
        "-f",
        help="Format: json, markdown",
    ),
    output: Optional[str] = typer.Option(
        None,
        "--out",
        "--output",
        "-o",
        help="Output file path (default: ~/.truthcast/exports)",
    ),
    stdout: bool = typer.Option(
        False,
        "--stdout",
        help="Write export content to stdout",
    ),
) -> None:
    """Export a history record as JSON or Markdown."""
    config = get_global_config()

    if not record_id:
        record_id = get_state_value("bound_record_id") or None
    if not record_id:
        typer.echo(_emoji('❌', '[ERROR]') + " 缺少 record_id. 用法: truthcast export --record-id <record_id>", err=True)
        typer.echo("   或先用 'truthcast state bind <record_id>' 绑定默认记录", err=True)
        raise typer.Exit(1)

    fmt = (format_type or "").strip().lower()
    if fmt not in {"json", "markdown", "md"}:
        typer.echo(f"{_emoji('❌', '[ERROR]')} 不支持的导出格式: {format_type} (支持: json, markdown)", err=True)
        raise typer.Exit(1)

    client = APIClient(base_url=config.api_base, timeout=config.timeout, retry_times=config.retry_times)
    try:
        history_detail = client.get(f"/history/{record_id}")
    except APIError as e:
        typer.echo(e.user_friendly_message(), err=True)
        raise typer.Exit(1)
    finally:
        client.close()

    if fmt == "json":
        content = json.dumps(history_detail, ensure_ascii=False, indent=2)
        ext = "json"
    else:
        content = _to_markdown(history_detail)
        ext = "md"

    if stdout:
        typer.echo(content)
        return

    out_path = Path(output) if output else (_default_export_dir() / f"truthcast_{record_id}.{ext}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")

    try:
        update_state("last_export_path", str(out_path))
    except Exception:
        pass

    typer.echo(f"{_emoji('✅', '[SUCCESS]')} 已导出: {out_path}")
