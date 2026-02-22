"""
LLM 驱动的报告生成模块

功能：
- 生成自然语言摘要
- 深度分析可疑点
- 主张级结论优化
- 风险评级理由
"""

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

try:
    # Windows 环境可能缺少 tzdata；因此 ZoneInfo 仅作为“可用则用”的增强
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore

import httpx

from app.core.logger import get_logger
from app.schemas.detect import ClaimItem, EvidenceItem
from app.services.json_utils import safe_json_loads, serialize_for_json

logger = get_logger(__name__)

REPORT_LLM_ENABLED = os.getenv("TRUTHCAST_REPORT_LLM_ENABLED", "false").lower() == "true"
REPORT_LLM_MODEL = os.getenv("TRUTHCAST_REPORT_LLM_MODEL", "")
REPORT_LLM_BASE_URL = os.getenv("TRUTHCAST_LLM_BASE_URL", "https://api.openai.com/v1")
REPORT_LLM_API_KEY = os.getenv("TRUTHCAST_LLM_API_KEY", "")
REPORT_TIMEOUT_SEC = int(os.getenv("TRUTHCAST_REPORT_TIMEOUT_SEC", "30"))
DEBUG_REPORT = os.getenv("TRUTHCAST_DEBUG_REPORT", "true").lower() == "true"


def _get_current_time_context() -> str:
    """获取当前时间上下文"""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y年%m月%d日 %H:%M UTC")


def _record_report_trace(stage: str, payload: dict[str, Any]) -> None:
    """记录报告生成 trace 日志"""
    if not DEBUG_REPORT:
        return

    try:
        current_file = os.path.abspath(__file__)
        services_dir = os.path.dirname(current_file)
        app_dir = os.path.dirname(services_dir)
        project_root = os.path.dirname(app_dir)

        debug_dir = os.path.join(project_root, "debug")
        os.makedirs(debug_dir, exist_ok=True)
        trace_file = os.path.join(debug_dir, "report_trace.jsonl")

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            "payload": serialize_for_json(payload),
        }
        with open(trace_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.error("写入 report trace 失败: %s", exc)


def _build_claim_evidence_summary(
    claims: list[ClaimItem],
    evidence_alignments: list[dict],
) -> str:
    """构建主张与证据摘要"""
    lines = []
    for i, (claim, alignment) in enumerate(zip(claims, evidence_alignments)):
        lines.append(f"\n### 主张 {claim.claim_id}")
        lines.append(f"内容: {claim.claim_text}")
        
        if claim.entity:
            lines.append(f"实体: {claim.entity}")
        if claim.time:
            lines.append(f"时间: {claim.time}")
        if claim.value:
            lines.append(f"数值: {claim.value}")
        
        stance = alignment.get("final_stance", "insufficient")
        notes = alignment.get("notes", [])
        evidences = alignment.get("evidences", [])
        
        lines.append(f"最终立场: {stance}")
        
        if evidences:
            lines.append(f"证据数量: {len(evidences)}")
            for ev in evidences[:3]:
                ev_stance = getattr(ev, "stance", "unknown")
                ev_title = getattr(ev, "title", "")[:50]
                confidence = getattr(ev, "alignment_confidence", None)
                conf_str = f"{confidence:.2f}" if confidence is not None else "N/A"
                lines.append(f"  - [{ev_stance}] {ev_title} (置信度: {conf_str})")
        
        if notes:
            lines.append(f"分析笔记: {'; '.join(notes[:2])}")
    
    return "\n".join(lines)


def generate_report_with_llm(
    original_text: str,
    claims: list[ClaimItem],
    evidence_alignments: list[dict],
    risk_score: int,
    scenario: str,
) -> dict[str, Any] | None:
    """
    LLM 驱动报告生成
    
    Args:
        original_text: 原始新闻文本
        claims: 主张列表
        evidence_alignments: 每条主张的对齐结果
        risk_score: 初始风险分数
        scenario: 场景类型
    
    Returns:
        生成结果或 None（失败时）
    """
    if not REPORT_LLM_ENABLED or not REPORT_LLM_API_KEY:
        logger.info("[Report] LLM not enabled or no API key, using rule fallback")
        _record_report_trace("input", {
            "path": "rule_fallback",
            "reason": "llm_disabled" if not REPORT_LLM_ENABLED else "no_api_key",
            "claims_count": len(claims),
            "risk_score": risk_score,
        })
        return None

    # ---- Runtime 时间上下文（用于缓解 LLM 将“2026”等年份误判为未来的偏置）----
    current_time = _get_current_time_context()
    now_utc = datetime.now(timezone.utc)
    tz_name = os.getenv("TRUTHCAST_REPORT_TZ", "Asia/Hong_Kong").strip() or "Asia/Hong_Kong"
    local_tz = None
    if ZoneInfo is not None:
        try:
            local_tz = ZoneInfo(tz_name)
        except Exception:
            local_tz = None
    # 最终兜底：固定 UTC+8（避免因 tzdata 缺失导致运行时异常）
    if local_tz is None:
        local_tz = timezone(timedelta(hours=8))
        tz_name = "UTC+08:00"
    now_local = now_utc.astimezone(local_tz)
    runtime_utc_iso = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    runtime_local_str = now_local.strftime("%Y-%m-%d %H:%M")
    runtime_date_local = now_local.strftime("%Y-%m-%d")
    claim_evidence_summary = _build_claim_evidence_summary(claims, evidence_alignments)
    
    text_preview = original_text[:800] if len(original_text) > 800 else original_text

    prompt = f"""你是事实核查专家，基于以下信息生成综合报告。

【系统运行时当前时间（权威基准）】
- runtime_utc: {runtime_utc_iso}
- runtime_local: {runtime_local_str} ({tz_name})
- runtime_date_local: {runtime_date_local}

【时间判断硬规则（必须遵守）】
1) 仅当文本中出现的日期严格晚于 runtime_date_local（例如 >= {runtime_date_local} 的次日）时，才允许使用“未来/预测性报道/虚构时间/时间指向未来/未来新闻”等表述。
2) 若文本日期等于或早于 runtime_date_local，禁止使用上述表述；此时只能描述为“同日/近期/时间信息清晰/时间信息缺失”。
3) 禁止使用模型训练截止时间或常识先验推断“某年份一定是未来”。必须以 runtime_date_local 为准。

【当前时间（兼容旧格式）】
{current_time}

【原始文本】
{text_preview}

【提取的主张】({len(claims)} 条)
{claim_evidence_summary}

【分析结果】
- 场景类型: {scenario}
- 初始风险分数: {risk_score}

【输出要求】
1. summary: 综合摘要（80-150字）
   - 结合原始文本的语气、措辞
   - 突出关键发现和风险点
   - 仅当你能明确指出“文本中的具体日期”与 runtime_date_local 存在矛盾时，才讨论“旧闻新炒/时间错位/未来报道”；否则不要主动引入这些概念

2. suspicious_points: 2-4个可疑点
   - 主张与证据的矛盾
   - 原始文本中的情绪化措辞
   - 时间/数据/来源的可疑之处

3. claim_conclusions: 每条主张的结论（30-50字）
   - 结合原始文本上下文
   - 具体的核查结论

4. risk_reasoning: 风险评级理由（50字以内）
   - 综合各方因素的理由

【自检】
输出前请自查：若你没有证据表明文本日期晚于 runtime_date_local，则 summary 与 suspicious_points 中不得出现：未来/预测性报道/虚构时间/时间指向未来/未来新闻。

输出严格 JSON 格式：
{{
  "summary": "综合摘要...",
  "suspicious_points": ["可疑点1", "可疑点2"],
  "claim_conclusions": [
    {{"claim_id": "c1", "conclusion": "该主张的结论..."}}
  ],
  "risk_reasoning": "风险评级理由..."
}}
"""

    # 记录输入
    _record_report_trace("input", {
        "path": "llm",
        "original_text_preview": text_preview,
        "claims_count": len(claims),
        "evidence_alignments_count": len(evidence_alignments),
        "risk_score": risk_score,
        "scenario": scenario,
        "current_time": current_time,
        "runtime_utc": runtime_utc_iso,
        "runtime_local": f"{runtime_local_str} ({tz_name})",
        "runtime_date_local": runtime_date_local,
    })

    system_prompt = "你是事实核查专家，擅长分析新闻文本的可信度并生成专业报告。输出必须为严格的 JSON 格式。"
    user_prompt = prompt

    headers = {
        "Authorization": f"Bearer {REPORT_LLM_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": REPORT_LLM_MODEL or "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.5,
        "max_tokens": 4000,
    }

    _record_report_trace("llm_request", {
        "endpoint": f"{REPORT_LLM_BASE_URL}/chat/completions",
        "model": REPORT_LLM_MODEL or "gpt-4o-mini",
        "timeout": REPORT_TIMEOUT_SEC,
        "temperature": 0.5,
        "max_tokens": 4000,
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "user_prompt_length": len(user_prompt),
    })

    try:
        with httpx.Client(timeout=REPORT_TIMEOUT_SEC) as client:
            resp = client.post(
                f"{REPORT_LLM_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            raw_body = resp.json()
            content_raw = raw_body["choices"][0]["message"]["content"]
            content = content_raw.strip()

            # 记录原始响应
            _record_report_trace("llm_response_raw", {
                "status_code": resp.status_code,
                "content_length": len(content_raw),
                "content_preview": content_raw[:500],
            })

            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            parsed = safe_json_loads(content, "report_generation")
            if parsed:
                result = _normalize_llm_output(parsed, claims)
                # 记录解析后的结果
                _record_report_trace("llm_response_parsed", {
                    "path": "llm",
                    "parsed": parsed,
                    "normalized": result,
                })
                # 记录最终输出
                _record_report_trace("output", {
                    "path": "llm",
                    "summary": result.get("summary", ""),
                    "suspicious_points": result.get("suspicious_points", []),
                    "claim_conclusions": result.get("claim_conclusions", {}),
                    "risk_reasoning": result.get("risk_reasoning", ""),
                })
                logger.info("[Report] LLM report generation succeeded")
                return result
            else:
                logger.warning("[Report] LLM response JSON parse failed")
                _record_report_trace("llm_parse_error", {
                    "raw_content": content[:1000],
                    "error": "JSON parse failed",
                })
                return None

    except httpx.TimeoutException:
        logger.warning("[Report] LLM request timed out after %ss", REPORT_TIMEOUT_SEC)
        _record_report_trace("llm_timeout", {
            "timeout": REPORT_TIMEOUT_SEC,
            "error": "TimeoutException",
        })
        return None
    except Exception as e:
        logger.warning("[Report] LLM request failed: %s", e)
        _record_report_trace("llm_error", {
            "error_type": type(e).__name__,
            "error_message": str(e),
        })
        return None


def _normalize_llm_output(parsed: dict, claims: list[ClaimItem]) -> dict[str, Any]:
    """标准化 LLM 输出"""
    summary = str(parsed.get("summary", "")).strip()
    
    suspicious_points = []
    for point in parsed.get("suspicious_points", [])[:4]:
        if point and isinstance(point, str):
            suspicious_points.append(point)
    
    claim_conclusions = {}
    for item in parsed.get("claim_conclusions", []):
        claim_id = str(item.get("claim_id", ""))
        conclusion = str(item.get("conclusion", "")).strip()
        if claim_id and conclusion:
            claim_conclusions[claim_id] = conclusion
    
    for claim in claims:
        if claim.claim_id not in claim_conclusions:
            claim_conclusions[claim.claim_id] = ""
    
    risk_reasoning = str(parsed.get("risk_reasoning", "")).strip()
    
    return {
        "summary": summary,
        "suspicious_points": suspicious_points,
        "claim_conclusions": claim_conclusions,
        "risk_reasoning": risk_reasoning,
    }


def generate_fallback_report(
    claims: list[ClaimItem],
    evidence_alignments: list[dict],
    risk_score: int,
) -> dict[str, Any]:
    """规则兜底报告生成"""
    _record_report_trace("fallback_input", {
        "path": "rule",
        "claims_count": len(claims),
        "risk_score": risk_score,
    })
    
    support_count = sum(1 for a in evidence_alignments if a.get("final_stance") == "support")
    refute_count = sum(1 for a in evidence_alignments if a.get("final_stance") == "refute")
    insufficient_count = sum(1 for a in evidence_alignments if a.get("final_stance") == "insufficient")
    
    total_evidence = sum(len(a.get("evidences", [])) for a in evidence_alignments)
    
    if risk_score >= 75:
        summary = f"经核查，该内容可信度较高。共分析 {len(claims)} 条主张，其中 {support_count} 条获证据支持，未发现明显矛盾。"
        risk_reasoning = "证据充分，主张与证据一致，无明显风险点。"
    elif risk_score >= 55:
        summary = f"经核查，该内容需要补充语境。共分析 {len(claims)} 条主张，{insufficient_count} 条证据不足，建议进一步核实。"
        risk_reasoning = "部分主张证据不足，存在信息不完整的情况。"
    elif risk_score >= 35:
        summary = f"经核查，该内容存在可疑之处。共分析 {len(claims)} 条主张，{refute_count} 条被证据反驳，需谨慎对待。"
        risk_reasoning = "部分主张与证据矛盾，存在虚假信息风险。"
    else:
        summary = f"经核查，该内容存在较高风险。共分析 {len(claims)} 条主张，{refute_count} 条被证据反驳，建议核实来源。"
        risk_reasoning = "多条主张与证据矛盾，虚假信息风险较高。"
    
    suspicious_points = []
    for alignment in evidence_alignments:
        claim_obj = alignment.get("claim")
        claim_id = claim_obj.claim_id if claim_obj else "?"
        if alignment.get("final_stance") == "refute":
            suspicious_points.append(f"{claim_id} 被证据直接反驳")
        elif alignment.get("final_stance") == "insufficient":
            suspicious_points.append(f"{claim_id} 缺乏有效证据支持")
    
    if not suspicious_points:
        suspicious_points = ["暂未发现明显矛盾点，建议持续关注。"]
    
    claim_conclusions = {}
    for alignment in evidence_alignments:
        claim = alignment.get("claim")
        if claim:
            stance = alignment.get("final_stance", "insufficient")
            notes = alignment.get("notes", [])
            if stance == "refute":
                claim_conclusions[claim.claim_id] = "该主张与证据存在矛盾，建议谨慎采信。"
            elif stance == "support":
                claim_conclusions[claim.claim_id] = "该主张获得证据支持，可信度较高。"
            else:
                claim_conclusions[claim.claim_id] = "该主张证据不足，需进一步核实。"
    
    result = {
        "summary": summary,
        "suspicious_points": suspicious_points[:4],
        "claim_conclusions": claim_conclusions,
        "risk_reasoning": risk_reasoning,
    }
    
    _record_report_trace("fallback_output", {
        "path": "rule",
        "summary": summary,
        "suspicious_points": suspicious_points[:4],
        "support_count": support_count,
        "refute_count": refute_count,
        "insufficient_count": insufficient_count,
    })
    
    return result
