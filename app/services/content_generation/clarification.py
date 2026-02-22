"""
澄清稿生成模块

根据检测结果和舆情预演结果，生成三种长度的澄清稿：
- 短版：约100字，适合快速传播
- 中版：约300字，平衡信息量与可读性
- 长版：约600字，适合正式发布
"""

import json
import os
from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.logger import get_logger
from app.schemas.detect import (
    ClarificationContent,
    ClarificationStyle,
    ReportResponse,
    SimulateResponse,
)
from app.services.json_utils import safe_json_loads, serialize_for_json

logger = get_logger(__name__)

# 配置
CONTENT_LLM_ENABLED = os.getenv("TRUTHCAST_CONTENT_LLM_ENABLED", "false").lower() == "true"
CONTENT_LLM_MODEL = os.getenv("TRUTHCAST_CONTENT_LLM_MODEL", "")
CONTENT_LLM_BASE_URL = os.getenv("TRUTHCAST_CONTENT_LLM_BASE_URL", os.getenv("TRUTHCAST_LLM_BASE_URL", "https://api.openai.com/v1"))
CONTENT_LLM_API_KEY = os.getenv("TRUTHCAST_CONTENT_LLM_API_KEY", os.getenv("TRUTHCAST_LLM_API_KEY", ""))
CONTENT_TIMEOUT_SEC = int(os.getenv("TRUTHCAST_CONTENT_TIMEOUT_SEC", "45"))
DEBUG_CONTENT = os.getenv("TRUTHCAST_DEBUG_CONTENT", "true").lower() == "true"

# 字数限制
CLARIFICATION_SHORT_MAX = int(os.getenv("TRUTHCAST_CLARIFICATION_SHORT_MAX", "150"))
CLARIFICATION_MEDIUM_MAX = int(os.getenv("TRUTHCAST_CLARIFICATION_MEDIUM_MAX", "400"))
CLARIFICATION_LONG_MAX = int(os.getenv("TRUTHCAST_CLARIFICATION_LONG_MAX", "800"))


def _get_style_guidance(style: ClarificationStyle) -> str:
    """获取风格指导"""
    if style == ClarificationStyle.FORMAL:
        return "正式严肃，措辞严谨，强调权威证据来源，适合官方发布"
    elif style == ClarificationStyle.FRIENDLY:
        return "亲切友好，口语化表达，易于理解，适合社交媒体传播"
    else:  # NEUTRAL
        return "中性客观，平衡各方信息，避免情绪化表述"


def _build_claim_summary(report: ReportResponse) -> str:
    """构建主张摘要"""
    lines = []
    for cr in report.claim_reports:
        stance_zh = {
            "support": "支持",
            "oppose": "反对",
            "insufficient_evidence": "证据不足",
        }.get(cr.final_stance, cr.final_stance)
        
        lines.append(f"- 主张: {cr.claim.claim_text[:50]}...")
        lines.append(f"  立场: {stance_zh}")
        if cr.evidences:
            lines.append(f"  证据数: {len(cr.evidences)}")
    return "\n".join(lines)


def _build_simulation_summary(simulation: SimulateResponse | None) -> str:
    """构建舆情预演摘要"""
    if not simulation:
        return "无"
    
    lines = [
        f"- 情绪分布: {simulation.emotion_distribution}",
        f"- 立场分布: {simulation.stance_distribution}",
        f"- 叙事分支数: {len(simulation.narratives)}",
        f"- 应对建议摘要: {simulation.suggestion.summary[:100]}...",
    ]
    return "\n".join(lines)


def _record_trace(stage: str, payload: dict[str, Any]) -> None:
    """记录 debug trace"""
    if not DEBUG_CONTENT:
        return
    
    try:
        current_file = os.path.abspath(__file__)
        services_dir = os.path.dirname(current_file)
        content_dir = os.path.dirname(services_dir)
        app_dir = os.path.dirname(content_dir)
        project_root = os.path.dirname(app_dir)
        
        debug_dir = os.path.join(project_root, "debug")
        os.makedirs(debug_dir, exist_ok=True)
        trace_file = os.path.join(debug_dir, "content_trace.jsonl")
        
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "module": "clarification",
            "stage": stage,
            "payload": serialize_for_json(payload),
        }
        with open(trace_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.error("写入 content trace 失败: %s", exc)


async def _call_llm(prompt: str) -> dict | None:
    """调用 LLM 生成澄清稿"""
    if not CONTENT_LLM_ENABLED or not CONTENT_LLM_API_KEY:
        logger.info("[Clarification] LLM not enabled or no API key")
        return None
    
    headers = {
        "Authorization": f"Bearer {CONTENT_LLM_API_KEY}",
        "Content-Type": "application/json",
    }
    
    system_prompt = "你是公关专家，擅长撰写澄清稿和应对文案。输出必须为严格的 JSON 格式。"
    user_prompt = prompt

    payload = {
        "model": CONTENT_LLM_MODEL or "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 8000,
    }
    
    _record_trace(
        "llm_request",
        {
            "base_url": CONTENT_LLM_BASE_URL,
            "model": payload.get("model"),
            "temperature": payload.get("temperature"),
            "max_tokens": payload.get("max_tokens"),
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
        },
    )
    
    try:
        async with httpx.AsyncClient(timeout=CONTENT_TIMEOUT_SEC) as client:
            response = await client.post(
                f"{CONTENT_LLM_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            result = safe_json_loads(content)
            _record_trace(
                "llm_response",
                {
                    "raw_content": content,
                    "result": result,
                },
            )
            return result
    except Exception as exc:
        logger.error("[Clarification] LLM 调用失败: %s", exc)
        _record_trace("llm_error", {"error": str(exc)})
        return None


def _fallback_clarification(
    report: ReportResponse,
    style: ClarificationStyle,
) -> ClarificationContent:
    """规则兜底生成澄清稿"""
    # 基于报告生成简化版澄清稿
    risk_label_zh = {
        "credible": "可信",
        "suspicious": "可疑",
        "high_risk": "高风险",
        "needs_context": "需要补充语境",
        "likely_misinformation": "疑似不实信息",
    }.get(report.risk_label, report.risk_label)
    
    # 短版
    short = f"经核实，该信息的可信度评估为「{risk_label_zh}」。"
    if report.suspicious_points:
        short += f"主要关注点：{report.suspicious_points[0][:30]}。"
    short += "建议以官方渠道发布的信息为准。"
    
    # 中版
    medium = f"针对近期传播的相关信息，经核查评估为「{risk_label_zh}」。"
    medium += f"风险等级：{report.risk_level}（满分100分中{report.risk_score}分）。"
    if report.suspicious_points:
        medium += f"主要疑点：{'；'.join(report.suspicious_points[:2])}。"
    medium += "请广大公众以官方渠道发布的信息为准，不传谣、不信谣。"
    
    # 长版
    long = f"【情况说明】\n\n"
    long += f"针对近期网络传播的相关信息，现就核查情况说明如下：\n\n"
    long += f"一、信息评估\n经核查，该信息的可信度评估为「{risk_label_zh}」，风险等级{report.risk_level}。\n\n"
    long += f"二、核查依据\n{report.summary}\n\n"
    if report.suspicious_points:
        long += f"三、主要疑点\n"
        for i, point in enumerate(report.suspicious_points, 1):
            long += f"{i}. {point}\n"
    long += f"\n四、建议\n请广大公众以官方渠道发布的信息为准，不传谣、不信谣，共同维护清朗网络空间。"
    
    return ClarificationContent(
        short=short[:CLARIFICATION_SHORT_MAX],
        medium=medium[:CLARIFICATION_MEDIUM_MAX],
        long=long[:CLARIFICATION_LONG_MAX],
    )


async def generate_clarification(
    original_text: str,
    report: ReportResponse,
    simulation: SimulateResponse | None,
    style: ClarificationStyle,
) -> ClarificationContent:
    """
    生成澄清稿
    
    Args:
        original_text: 原始新闻文本
        report: 检测报告
        simulation: 舆情预演结果
        style: 澄清稿风格
        
    Returns:
        ClarificationContent: 三种长度的澄清稿
    """
    logger.info("[Clarification] 开始生成澄清稿, 风格=%s", style)
    
    # 构建 prompt
    style_guidance = _get_style_guidance(style)
    claim_summary = _build_claim_summary(report)
    simulation_summary = _build_simulation_summary(simulation)
    
    text_preview = original_text[:500] if len(original_text) > 500 else original_text
    
    prompt = f"""你是公关专家，需要针对以下检测结果生成澄清稿。

【原始新闻】
{text_preview}

【检测结果】
- 风险等级: {report.risk_level} ({report.risk_label})
- 检测场景: {report.detected_scenario}
- 综合摘要: {report.summary}
- 可疑点: {report.suspicious_points}

【主张分析】
{claim_summary}

【舆情预演】（如有）
{simulation_summary}

【风格要求】
{style_guidance}

【输出要求】
生成三个版本的澄清稿：
1. short: 约100字，适合快速传播，突出核心信息
2. medium: 约300字，平衡信息量与可读性
3. long: 约600字，完整阐述，适合正式发布

输出严格 JSON 格式：
{{
  "short": "短版澄清稿...",
  "medium": "中版澄清稿...",
  "long": "长版澄清稿..."
}}
"""
    
    # 尝试 LLM 生成
    result = await _call_llm(prompt)
    
    if result and "short" in result and "medium" in result and "long" in result:
        return ClarificationContent(
            short=result["short"][:CLARIFICATION_SHORT_MAX],
            medium=result["medium"][:CLARIFICATION_MEDIUM_MAX],
            long=result["long"][:CLARIFICATION_LONG_MAX],
        )
    
    # 回退到规则生成
    logger.info("[Clarification] 使用规则兜底生成")
    return _fallback_clarification(report, style)
