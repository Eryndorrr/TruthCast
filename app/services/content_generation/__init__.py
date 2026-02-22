"""
应对内容生成服务模块

提供：
- 澄清稿生成
- FAQ 生成
- 多平台话术生成
"""

import os
from datetime import datetime, timezone
from typing import Any

from app.core.logger import get_logger
from app.schemas.detect import (
    ContentGenerateRequest,
    ContentGenerateResponse,
    ClarificationContent,
    ClarificationStyle,
    FAQItem,
    PlatformScript,
    Platform,
)

from .clarification import generate_clarification
from .faq import generate_faq
from .platform_scripts import generate_platform_scripts

logger = get_logger(__name__)

# 配置
CONTENT_LLM_ENABLED = os.getenv("TRUTHCAST_CONTENT_LLM_ENABLED", "false").lower() == "true"
CONTENT_LLM_MODEL = os.getenv("TRUTHCAST_CONTENT_LLM_MODEL", "")
CONTENT_LLM_BASE_URL = os.getenv("TRUTHCAST_CONTENT_LLM_BASE_URL", os.getenv("TRUTHCAST_LLM_BASE_URL", "https://api.openai.com/v1"))
CONTENT_LLM_API_KEY = os.getenv("TRUTHCAST_CONTENT_LLM_API_KEY", os.getenv("TRUTHCAST_LLM_API_KEY", ""))
CONTENT_TIMEOUT_SEC = int(os.getenv("TRUTHCAST_CONTENT_TIMEOUT_SEC", "45"))
DEBUG_CONTENT = os.getenv("TRUTHCAST_DEBUG_CONTENT", "true").lower() == "true"


async def generate_full_content(request: ContentGenerateRequest) -> ContentGenerateResponse:
    """
    生成完整应对内容
    
    Args:
        request: 内容生成请求
        
    Returns:
        ContentGenerateResponse: 完整内容响应
    """
    logger.info("[Content] 开始生成应对内容, 风格=%s, 平台数=%d", request.style, len(request.platforms))
    
    # 生成澄清稿
    clarification = await generate_clarification(
        original_text=request.text,
        report=request.report,
        simulation=request.simulation,
        style=request.style,
    )
    
    # 生成 FAQ
    faq = None
    if request.include_faq:
        faq = await generate_faq(
            original_text=request.text,
            report=request.report,
            simulation=request.simulation,
            count=request.faq_count,
        )
    
    # 生成多平台话术
    platform_scripts = await generate_platform_scripts(
        clarification=clarification,
        report=request.report,
        simulation=request.simulation,
        platforms=request.platforms,
    )
    
    # 构建响应
    response = ContentGenerateResponse(
        clarification=clarification,
        faq=faq,
        platform_scripts=platform_scripts,
        generated_at=datetime.now(timezone.utc).isoformat(),
        based_on={
            "risk_level": request.report.risk_level,
            "risk_label": request.report.risk_label,
            "scenario": request.report.detected_scenario,
            "claims_count": len(request.report.claim_reports),
            "style": request.style.value,
            "platforms": [p.value for p in request.platforms],
        },
    )
    
    logger.info("[Content] 应对内容生成完成")
    return response


async def generate_clarification_only(request: ContentGenerateRequest) -> ClarificationContent:
    """仅生成澄清稿"""
    return await generate_clarification(
        original_text=request.text,
        report=request.report,
        simulation=request.simulation,
        style=request.style,
    )


async def generate_faq_only(request: ContentGenerateRequest) -> list[FAQItem]:
    """仅生成 FAQ"""
    return await generate_faq(
        original_text=request.text,
        report=request.report,
        simulation=request.simulation,
        count=request.faq_count,
    )


async def generate_platform_scripts_only(request: ContentGenerateRequest) -> list[PlatformScript]:
    """仅生成多平台话术"""
    # 说明：多平台话术生成需要“澄清稿”作为输入。
    # - 若前端已生成澄清稿，则可通过 request.clarification 复用，避免重复调用。
    # - 若未提供，则使用基于 report 的轻量规则摘要构造一个澄清稿占位（不再强制调用 generate_clarification）。
    clarification = request.clarification
    if clarification is None:
        summary = (request.report.summary or "").strip()
        suspicious = request.report.suspicious_points or []
        suspicious_text = "；".join([s for s in suspicious if s])

        # 简单规则化澄清稿：保证平台话术可生成且不额外触发澄清稿生成链路
        short = summary or "针对网传信息，我们已完成核查：当前缺乏可靠证据支持相关说法，请勿轻信与传播。"
        medium_parts = [
            f"【核查结论】{summary}" if summary else "【核查结论】目前证据不足，建议保持谨慎并等待权威信息。",
            f"【可疑点】{suspicious_text}" if suspicious_text else "【可疑点】信息来源不明、缺乏可核查细节或权威出处。",
            "【建议】不转发、不传播；如需引用，请附上权威来源链接。",
        ]
        medium = "\n".join([p for p in medium_parts if p]).strip()
        long_parts = [
            "【说明】我们对网传内容进行了要点梳理与证据核对，结论基于当前可获得的信息。",
            medium,
            "【后续】如出现新的权威通报或可靠证据，将及时更新。",
        ]
        long = "\n\n".join([p for p in long_parts if p]).strip()

        clarification = ClarificationContent(short=short[:300], medium=medium[:1200], long=long[:3000])
    
    return await generate_platform_scripts(
        clarification=clarification,
        report=request.report,
        simulation=request.simulation,
        platforms=request.platforms,
    )
