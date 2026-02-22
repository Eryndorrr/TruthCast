"""
FAQ 生成模块

根据检测结果和舆情预演结果，生成常见问题解答。
"""

import json
import os
from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.logger import get_logger
from app.schemas.detect import (
    FAQItem,
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

# FAQ 配置
FAQ_DEFAULT_COUNT = int(os.getenv("TRUTHCAST_FAQ_DEFAULT_COUNT", "5"))


def _build_claim_evidence_summary(report: ReportResponse) -> str:
    """构建主张与证据摘要"""
    lines = []
    for cr in report.claim_reports:
        lines.append(f"Q: {cr.claim.claim_text}")
        stance_zh = {
            "support": "支持",
            "oppose": "反对",
            "insufficient_evidence": "证据不足",
        }.get(cr.final_stance, cr.final_stance)
        lines.append(f"A: 核查结果为「{stance_zh}」")
        if cr.evidences:
            for ev in cr.evidences[:2]:
                lines.append(f"  - {ev.title}: {ev.summary[:50]}...")
        lines.append("")
    return "\n".join(lines)


def _build_predicted_concerns(simulation: SimulateResponse | None) -> str:
    """构建预测关注点"""
    if not simulation:
        return "暂无舆情预测"
    
    concerns = []
    
    # 从情绪分布提取关注点
    if simulation.emotion_drivers:
        concerns.extend(simulation.emotion_drivers[:2])
    
    # 从叙事分支提取关注点
    for narrative in simulation.narratives[:2]:
        if narrative.trigger_keywords:
            concerns.extend(narrative.trigger_keywords[:2])
    
    return "、".join(concerns[:5]) if concerns else "暂无特殊关注点"


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
            "module": "faq",
            "stage": stage,
            "payload": serialize_for_json(payload),
        }
        with open(trace_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.error("写入 content trace 失败: %s", exc)


async def _call_llm(prompt: str) -> dict | None:
    """调用 LLM 生成 FAQ"""
    if not CONTENT_LLM_ENABLED or not CONTENT_LLM_API_KEY:
        logger.info("[FAQ] LLM not enabled or no API key")
        return None
    
    headers = {
        "Authorization": f"Bearer {CONTENT_LLM_API_KEY}",
        "Content-Type": "application/json",
    }
    
    system_prompt = "你是事实核查专家，擅长生成常见问题解答。输出必须为严格的 JSON 格式。"
    user_prompt = prompt

    payload = {
        "model": CONTENT_LLM_MODEL or "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.6,
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
        logger.error("[FAQ] LLM 调用失败: %s", exc)
        _record_trace("llm_error", {"error": str(exc)})
        return None


def _fallback_faq(report: ReportResponse, count: int) -> list[FAQItem]:
    """规则兜底生成 FAQ"""
    faq_list = []
    
    # 核心 FAQ：信息是否属实
    risk_label_zh = {
        "credible": "可信",
        "suspicious": "可疑",
        "high_risk": "高风险",
        "needs_context": "需要补充语境",
        "likely_misinformation": "疑似不实信息",
    }.get(report.risk_label, report.risk_label)
    
    faq_list.append(FAQItem(
        question="该信息是否属实？",
        answer=f"经核查评估，该信息的可信度为「{risk_label_zh}」。风险等级为{report.risk_level}（{report.risk_score}/100）。建议以官方渠道发布的信息为准。",
        category="core",
    ))
    
    # 从可疑点生成 FAQ
    for i, point in enumerate(report.suspicious_points[:2]):
        faq_list.append(FAQItem(
            question=f"关于「{point[:20]}...」的疑问？",
            answer=f"核查发现：{point}。建议进一步关注官方说明或权威媒体报道。",
            category="detail",
        ))
    
    # 从主张生成 FAQ
    for cr in report.claim_reports[:2]:
        stance_zh = {
            "support": "有证据支持",
            "oppose": "存在反驳证据",
            "insufficient_evidence": "证据不足",
        }.get(cr.final_stance, cr.final_stance)
        
        faq_list.append(FAQItem(
            question=f"「{cr.claim.claim_text[:25]}...」是真的吗？",
            answer=f"该主张经核查{stance_zh}。" + (f"参考证据：{cr.evidences[0].title}" if cr.evidences else ""),
            category="detail",
        ))
    
    # 背景 FAQ
    faq_list.append(FAQItem(
        question="如何获取最新权威信息？",
        answer="建议关注官方发布渠道，如政府网站、权威媒体官方账号等。避免从不明来源转发信息。",
        category="background",
    ))
    
    return faq_list[:count]


async def generate_faq(
    original_text: str,
    report: ReportResponse,
    simulation: SimulateResponse | None,
    count: int,
) -> list[FAQItem]:
    """
    生成 FAQ
    
    Args:
        original_text: 原始新闻文本
        report: 检测报告
        simulation: 舆情预演结果
        count: FAQ 条目数量
        
    Returns:
        list[FAQItem]: FAQ 列表
    """
    logger.info("[FAQ] 开始生成 FAQ, 条数=%d", count)
    
    claim_evidence_summary = _build_claim_evidence_summary(report)
    predicted_concerns = _build_predicted_concerns(simulation)
    
    text_preview = original_text[:400] if len(original_text) > 400 else original_text
    
    prompt = f"""你是事实核查专家，需要针对以下信息生成常见问题解答。

【原始新闻】
{text_preview}

【检测结果】
- 风险等级: {report.risk_level} ({report.risk_label})
- 综合摘要: {report.summary}

【主张与证据】
{claim_evidence_summary}

【舆情预测热点】
{predicted_concerns}

【输出要求】
生成 {count} 条 FAQ，每条包含：
- question: 用户可能提出的问题（15-30字）
- answer: 基于证据的回答（50-100字）
- category: 分类（core=核心问题/detail=细节/background=背景）

输出严格 JSON 格式：
{{
  "faq": [
    {{"question": "...", "answer": "...", "category": "core"}},
    ...
  ]
}}
"""
    
    # 尝试 LLM 生成
    result = await _call_llm(prompt)
    
    if result and "faq" in result:
        faq_list = []
        for item in result["faq"][:count]:
            faq_list.append(FAQItem(
                question=item.get("question", ""),
                answer=item.get("answer", ""),
                category=item.get("category", "general"),
            ))
        if faq_list:
            return faq_list
    
    # 回退到规则生成
    logger.info("[FAQ] 使用规则兜底生成")
    return _fallback_faq(report, count)
