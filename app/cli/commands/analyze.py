"""Analyze command - Full pipeline analysis."""

import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import typer

from app.cli.client import APIClient, APIError
from app.cli.lib.state_manager import update_state
from app.cli.config import get_config


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


def _read_input(file_path: Optional[str]) -> str:
    """
    Read input text from file or stdin.
    
    Args:
        file_path: Optional file path to read from
        
    Returns:
        Input text
    """
    if file_path:
        # Read from file
        try:
            path = Path(file_path)
            if not path.exists():
                typer.echo(f"{_emoji('❌', '[ERROR]')} 文件不存在: {file_path}", err=True)
                raise typer.Exit(1)
            
            text = path.read_text(encoding="utf-8")
            return text.strip()
        except Exception as e:
            typer.echo(f"{_emoji('❌', '[ERROR]')} 读取文件失败: {e}", err=True)
            raise typer.Exit(1)
    else:
        # Read from stdin
        if sys.stdin.isatty():
            typer.echo(f"{_emoji('💡', '[INFO]')} 提示: 请输入待分析文本 (Ctrl+D 结束输入):", err=True)
        
        try:
            text = sys.stdin.read()
            return text.strip()
        except KeyboardInterrupt:
            typer.echo(f"\n{_emoji('❌', '[ERROR]')} 用户中断", err=True)
            raise typer.Exit(0)


def _format_text_output(result: Dict[str, Any]) -> str:
    """
    Format analysis result as human-readable text.
    
    Args:
        result: Complete analysis result from /detect/report
        
    Returns:
        Formatted text output
    """
    lines = []
    
    # Header
    lines.append(f"{_emoji('✅', '[SUCCESS]')} 分析完成\n")
    
    # Risk assessment
    risk_label = result.get("risk_label", "未知")
    risk_score = result.get("risk_score", 0)
    lines.append(f"风险评估: {risk_label} (风险分数: {risk_score}/100)")
    
    # Claims and evidence count
    claim_reports = result.get("claim_reports", [])
    total_claims = len(claim_reports)
    
    # Count total evidences
    total_evidences = 0
    for claim_report in claim_reports:
        total_evidences += len(claim_report.get("evidences", []))
    
    lines.append(f"主张数量: {total_claims} 条")
    lines.append(f"证据数量: {total_evidences} 条")
    
    # Record ID (if present)
    record_id = result.get("record_id")
    if record_id:
        lines.append(f"记录ID: {record_id}")
    
    lines.append("")
    
    # Summary
    summary = result.get("summary", "")
    if summary:
        lines.append("[综合结论]")
        lines.append(summary)
        lines.append("")
    
    # Suspicious points
    suspicious_points = result.get("suspicious_points", [])
    if suspicious_points:
        lines.append("[可疑点]")
        for i, point in enumerate(suspicious_points, 1):
            lines.append(f"  {i}. {point}")
        lines.append("")
    
    # Detected scenario and evidence domains
    detected_scenario = result.get("detected_scenario")
    evidence_domains = result.get("evidence_domains", [])
    
    if detected_scenario:
        lines.append(f"[识别场景] {detected_scenario}")
    
    if evidence_domains:
        domains_str = ", ".join(evidence_domains)
        lines.append(f"[证据覆盖域] {domains_str}")
    
    return "\n".join(lines)


def analyze(
    file: Optional[str] = typer.Option(
        None,
        "-f",
        "--file",
        help="输入文件路径 (不指定则从 stdin 读取)",
    ),
) -> None:
    """
    分析文本可信度 (完整流水线).
    
    执行完整分析流程:
    - 风险快照 (可信度评估)
    - 主张抽取
    - 证据检索
    - 证据对齐
    - 综合报告生成
    
    默认输出人类可读格式,使用 --json 输出 JSON 格式.
    
    示例:
    
      truthcast analyze -f news.txt
      
      cat news.txt | truthcast analyze
      
      truthcast --json analyze -f news.txt
    """
    config = get_config()
    
    # Read input
    try:
        text = _read_input(file)
    except typer.Exit:
        raise
    
    if not text:
        typer.echo(f"{_emoji('❌', '[ERROR]')} 输入为空", err=True)
        raise typer.Exit(1)
    
    # Create API client
    client = APIClient(
        base_url=config.api_base,
        timeout=config.timeout,
        retry_times=config.retry_times,
    )
    
    try:
        # Step 1: Risk snapshot (detect)
        if config.output_format != "json":
            typer.echo(f"{_emoji('🔍', '[1/4]')} 正在分析风险...", err=True)
        detect_result = client.post("/detect", json={"text": text})
        
        # Step 2: Extract claims
        if config.output_format != "json":
            typer.echo(f"{_emoji('📋', '[2/4]')} 正在抽取主张...", err=True)
        claims_result = client.post("/detect/claims", json={"text": text})
        claims = claims_result.get("claims", [])
        
        # Step 3: Retrieve evidence
        if config.output_format != "json":
            typer.echo(f"{_emoji('🔎', '[3/4]')} 正在检索证据...", err=True)
        evidence_result = client.post(
            "/detect/evidence",
            json={"text": text, "claims": claims},
        )
        evidences = evidence_result.get("evidences", [])
        
        # Step 4: Generate report
        if config.output_format != "json":
            typer.echo(f"{_emoji('📊', '[4/4]')} 正在生成报告...", err=True)
        report_result = client.post(
            "/detect/report",
            json={
                "text": text,
                "claims": claims,
                "evidences": evidences,
                "detect_data": {
                    "label": detect_result.get("label"),
                    "confidence": detect_result.get("confidence"),
                    "score": detect_result.get("score"),
                    "reasons": detect_result.get("reasons"),
                },
            },
        )
        
        # Save record_id to state if present
        record_id = report_result.get("record_id")
        if record_id:
            update_state("last_record_id", record_id)
            update_state("last_api_base", config.api_base)
        
        # Output result
        if config.output_format == "json":
            # JSON output to stdout
            print(json.dumps(report_result, ensure_ascii=False, indent=2))
        else:
            # Human-readable text output
            output = _format_text_output(report_result)
            print(output)
        
    except APIError as e:
        typer.echo(e.user_friendly_message(), err=True)
        raise typer.Exit(1)
    except KeyboardInterrupt:
        typer.echo(f"\n{_emoji('❌', '[ERROR]')} 用户中断", err=True)
        raise typer.Exit(0)
    except Exception as e:
        typer.echo(f"{_emoji('❌', '[ERROR]')} 未知错误: {e}", err=True)
        raise typer.Exit(1)
    finally:
        client.close()
