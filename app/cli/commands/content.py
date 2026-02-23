"""Content command - Generate response content."""

import json
import logging
import typer
from typing import Optional
from pathlib import Path

from app.cli.client import APIClient, APIError
from app.cli.config import get_config

logger = logging.getLogger(__name__)

PLATFORM_LABELS = {
    "weibo": "[Weibo]",
    "wechat": "[WeChat]",
    "xiaohongshu": "[XiaoHongShu]",
    "douyin": "[Douyin]",
    "kuaishou": "[Kuaishou]",
    "bilibili": "[BiliBili]",
    "short_video": "[ShortVideo]",
    "news": "[News]",
    "official": "[Official]",
}

STYLE_ZH = {"formal": "formal", "friendly": "friendly", "neutral": "neutral"}

def _get_home_dir() -> Path:
    return Path.home()

def _save_content_to_file(record_id: str, content_data: dict) -> Path:
    home_dir = _get_home_dir()
    truthcast_dir = home_dir / ".truthcast"
    truthcast_dir.mkdir(exist_ok=True)
    
    file_path = truthcast_dir / f"content_{record_id}.md"
    md_lines = ["# Response Content Generation Report", ""]

    if "clarification" in content_data and content_data["clarification"]:
        clarif = content_data["clarification"]
        md_lines.extend(["## Clarification Statement", "", 
            f"**Style**: {STYLE_ZH.get(content_data.get('style', 'formal'), 'formal')}", "", 
            "### Short Version (100 words)", clarif.get("short", ""), "",
            "### Medium Version (300 words)", clarif.get("medium", ""), "",
            "### Long Version (600 words)", clarif.get("long", ""), "",
        ])

    if "faq" in content_data and content_data["faq"]:
        faq_list = content_data["faq"]
        md_lines.extend(["## FAQ", ""])
        for idx, faq_item in enumerate(faq_list, 1):
            md_lines.extend([
                f"### Q{idx}: {faq_item.get('question', '')}",
                faq_item.get('answer', ''), "",
            ])

    if "platform_scripts" in content_data and content_data["platform_scripts"]:
        md_lines.extend(["## Platform-Specific Scripts", ""])
        for script in content_data["platform_scripts"]:
            platform = script.get("platform", "unknown")
            md_lines.extend([f"### {platform.upper()}", script.get("content", ""), ""])
            if script.get("tips"):
                md_lines.append("**Tips**:")
                for tip in script["tips"]:
                    md_lines.append(f"- {tip}")
                md_lines.append("")
    
    if "generated_at" in content_data:
        md_lines.extend(["---", "", f"Generated at: {content_data['generated_at']}"])
    
    newline = chr(10)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(newline.join(md_lines))
    return file_path

def _format_readable_output(response_data: dict, style: str, record_id: str) -> None:
    typer.echo()
    typer.secho("[CONTENT GENERATION COMPLETE]", fg=typer.colors.GREEN)
    typer.echo()
    
    if "clarification" in response_data and response_data["clarification"]:
        clarif = response_data["clarification"]
        typer.secho("[CLARIFICATION]", fg=typer.colors.BLUE)
        typer.echo(f"Style: {STYLE_ZH.get(style, style)}")
        typer.echo()
        typer.echo("Short version (100 words):")
        typer.echo(clarif.get("short", ""))
        typer.echo()
        typer.echo("Medium version (300 words):")
        typer.echo(clarif.get("medium", ""))
        typer.echo()
        typer.echo("Long version (600 words):")
        typer.echo(clarif.get("long", ""))
        typer.echo()
    
    if "faq" in response_data and response_data["faq"]:
        faq_list = response_data["faq"]
        typer.secho(f"[FAQ] ({len(faq_list)} items)", fg=typer.colors.BLUE)
        for idx, faq_item in enumerate(faq_list, 1):
            typer.echo(f"Q{idx}: {faq_item.get('question', '')}")
            typer.echo(f"A{idx}: {faq_item.get('answer', '')}")
            typer.echo()
    
    if "platform_scripts" in response_data and response_data["platform_scripts"]:
        typer.secho("[PLATFORM SCRIPTS]", fg=typer.colors.BLUE)
        for script in response_data["platform_scripts"]:
            platform = script.get("platform", "unknown")
            label = PLATFORM_LABELS.get(platform, f"[{platform.upper()}]")
            content_len = len(script.get("content", ""))
            typer.echo(f"{label} ({content_len} chars):")
            typer.echo(script.get("content", ""))
            if script.get("tips"):
                typer.echo("  Tips:")
                for tip in script["tips"]:
                    typer.echo(f"    - {tip}")
            typer.echo()
    
    try:
        file_path = _save_content_to_file(record_id, response_data)
        typer.secho(f"[SAVED]: {file_path}", fg=typer.colors.GREEN)
    except Exception as e:
        typer.secho(f"[SAVE FAILED]: {str(e)}", fg=typer.colors.YELLOW)

def content(
    record_id: str = typer.Option(..., "--record", "-r", help="Record ID from analysis history (required)"),
    style: str = typer.Option("formal", "--style", "-s", help="Style: formal, friendly, neutral (default: formal)"),
    platforms: Optional[str] = typer.Option(None, "--platforms", "-p", help="Comma-separated platform list"),
    faq: bool = typer.Option(True, "--faq/--no-faq", help="Include FAQ generation (default: true)"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON instead of human-readable format"),
) -> None:
    """Generate response content (clarification statements, FAQ, platform-specific scripts)."""
    
    from app.cli.main import get_global_config
    
    try:
        config = get_global_config()
        client = APIClient(base_url=config.api_base, timeout=config.timeout, retry_times=config.retry_times)
        
        typer.echo(f"[Fetching analysis data...] (record_id: {record_id})")
        
        history_resp = client.get(f"/history/{record_id}")
        if not history_resp:
            typer.secho(f"[Error]: Record not found: {record_id}", fg=typer.colors.RED)
            raise typer.Exit(1)
        
        input_text = history_resp.get("input_text", "")
        report = history_resp.get("report")
        simulation = history_resp.get("simulation")
        
        if not report:
            typer.secho("[Error]: No report data found for this record", fg=typer.colors.RED)
            raise typer.Exit(1)
        
        typer.echo(f"[Generating response content...]")
        
        platforms_list = None
        if platforms:
            platforms_list = [p.strip() for p in platforms.split(",")]
        
        payload = {"text": input_text, "report": report, "style": style.lower(), "include_faq": faq, "faq_count": 5}
        
        if simulation:
            payload["simulation"] = simulation
        if platforms_list:
            payload["platforms"] = platforms_list
        
        response = client.post("/content/generate", json=payload)
        
        if json_output:
            typer.echo(json.dumps(response, ensure_ascii=False, indent=2))
        else:
            _format_readable_output(response, style, record_id)
    
    except APIError as e:
        msg = e.user_friendly_message() if hasattr(e, 'user_friendly_message') else str(e)
        typer.secho(f"[API Error]: {msg}", fg=typer.colors.RED)
        raise typer.Exit(1)
    except Exception as e:
        logger.exception("Unexpected error")
        typer.secho(f"[Error]: {str(e)}", fg=typer.colors.RED)
        raise typer.Exit(1)
