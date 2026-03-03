from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import os
from datetime import datetime, timezone

from app.core.logger import get_logger
from app.schemas.detect import (
    ClaimItem,
    EvidenceItem,
    NarrativeItem,
    ReportResponse,
    SimulateResponse,
    StrategyConfig,
)
from app.services.claim_extraction import extract_claims as extract_claims_with_fallback
from app.services.evidence_alignment import align_claim_with_evidence
from app.services.evidence_retrieval import detect_scenario
from app.services.evidence_summarization import summarize_evidence_for_claim
from app.services.opinion_simulation import simulate_opinion_with_llm
from app.services.report_generation import (
    generate_fallback_report,
    generate_report_with_llm,
)
from app.services.web_retrieval import infer_web_stance, search_web_evidence

logger = get_logger("truthcast.pipeline")


def extract_claims(
    text: str, strategy: StrategyConfig | None = None
) -> list[ClaimItem]:
    max_claims = strategy.max_claims if strategy else None
    return extract_claims_with_fallback(text, max_claims=max_claims)


def retrieve_evidence(
    claims: list[ClaimItem], strategy: StrategyConfig | None = None
) -> list[EvidenceItem]:
    evidences: list[EvidenceItem] = []
    evidence_idx = 1
    web_top_k = (
        strategy.evidence_per_claim
        if strategy
        else _int_env("TRUTHCAST_WEB_RETRIEVAL_TOPK", 6)
    )
    retrieved_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for claim in claims:
        web_ranked = search_web_evidence(claim.claim_text, top_k=web_top_k)
        if not web_ranked:
            evidences.append(
                EvidenceItem(
                    evidence_id=f"e{evidence_idx}",
                    claim_id=claim.claim_id,
                    title="未找到可信证据候选",
                    source="web-search",
                    url="https://example.com/no-evidence",
                    published_at="2026-02-10",
                    summary=f"该主张暂无可用联网证据：{claim.claim_text[:80]}",
                    stance="insufficient",
                    source_weight=0.2,
                    source_type="web_live",
                    retrieved_at=retrieved_at,
                    domain="general",
                    is_authoritative=False,
                )
            )
            evidence_idx += 1
            continue

        for web_item in web_ranked:
            stance = infer_web_stance(claim.claim_text, web_item)
            evidences.append(
                EvidenceItem(
                    evidence_id=f"e{evidence_idx}",
                    claim_id=claim.claim_id,
                    title=web_item.title,
                    source=web_item.source,
                    url=web_item.url,
                    published_at=web_item.published_at,
                    summary=web_item.summary,
                    stance=stance,
                    source_weight=web_item.relevance,
                    source_type="web_live",
                    retrieved_at=retrieved_at,
                    domain=web_item.domain,
                    is_authoritative=web_item.is_authoritative,
                    raw_snippet=web_item.raw_snippet,
                )
            )
            evidence_idx += 1

    return evidences


def build_report(
    claims: list[ClaimItem],
    evidences: list[EvidenceItem],
    original_text: str = "",
    strategy: StrategyConfig | None = None,
    source_url: str | None = None,
    source_title: str | None = None,
    source_publish_date: str | None = None,
) -> dict:
    """
    生成综合报告（LLM 可选 + 规则兜底）

    Args:
        claims: 主张列表
        evidences: 已对齐的证据列表（来自 evidence 阶段）
        original_text: 原始文本（用于 LLM 报告生成）
        strategy: 策略配置

    Returns:
        报告字典
    """
    by_claim: dict[str, list[EvidenceItem]] = defaultdict(list)
    for item in evidences:
        by_claim[item.claim_id].append(item)

    rank_alpha = _float_env(
        "TRUTHCAST_CLAIM_RANK_ALPHA", 0.25, min_value=0.0, max_value=2.0
    )
    non_topk_factor = _float_env(
        "TRUTHCAST_REPORT_NON_TOPK_FACTOR", 0.5, min_value=0.0, max_value=1.0
    )
    topk_raw = os.getenv("TRUTHCAST_REPORT_TOPK", "0").strip()
    try:
        report_topk = int(topk_raw)
    except ValueError:
        report_topk = 0
    if report_topk < 0:
        report_topk = 0
    score_log_enabled = _report_score_log_enabled()

    # score 表示风险程度，越高风险越大（0=安全，100=极高风险）
    score = 45
    suspicious_points: list[str] = []
    claim_reports = []

    if score_log_enabled:
        logger.info(
            "报告计分开始：base=%s claims=%s evidences=%s rank_alpha=%.2f topk=%s non_topk_factor=%.2f",
            score,
            len(claims),
            len(evidences),
            rank_alpha,
            report_topk,
            non_topk_factor,
        )

    # 直接使用已对齐的证据，不再执行摘要和对齐
    for idx, claim in enumerate(claims):
        aligned_items = by_claim.get(claim.claim_id, [])

        weighted = {"support": 0.0, "refute": 0.0, "insufficient": 0.0}
        rationales: list[str] = []

        for item in aligned_items:
            confidence = (
                item.alignment_confidence
                if item.alignment_confidence is not None
                else 0.5
            )
            weighted[item.stance] = weighted.get(item.stance, 0.0) + (
                item.source_weight * max(0.2, confidence)
            )
            if item.alignment_rationale:
                rationales.append(item.alignment_rationale)

        stance = max(weighted, key=lambda k: weighted[k])
        notes = [f"主立场：{stance}", f"证据数量：{len(aligned_items)}"]
        if rationales:
            notes.append(f"对齐结论：{rationales[0]}")

        if stance == "refute":
            score_delta_base = 12
            suspicious_point = f"{claim.claim_id} 被证据反驳"
        elif stance == "support":
            score_delta_base = -12
            suspicious_point = ""
        else:
            score_delta_base = 4
            suspicious_point = f"{claim.claim_id} 证据不足以形成明确支持"

        rank_weight = 1.0 / (1.0 + rank_alpha * idx)
        score_factor = rank_weight
        if report_topk > 0 and idx >= report_topk:
            score_factor *= non_topk_factor

        score_delta = _weighted_delta(score_delta_base, score_factor)
        notes.append(f"排序权重：{rank_weight:.2f}")
        if report_topk > 0 and idx >= report_topk:
            notes.append(f"TopK折扣后权重：{score_factor:.2f}")

        score += score_delta
        if score_log_enabled:
            logger.info(
                "报告计分明细：claim=%s rank=%s stance=%s base_delta=%s factor=%.3f delta=%s cumulative=%s evidence_count=%s",
                claim.claim_id,
                idx + 1,
                stance,
                score_delta_base,
                score_factor,
                score_delta,
                score,
                len(aligned_items),
            )
        if suspicious_point:
            suspicious_points.append(suspicious_point)

        claim_reports.append(
            {
                "claim": claim,
                "evidences": aligned_items,
                "final_stance": stance,
                "notes": notes,
            }
        )

    score = max(0, min(100, score))
    if score <= 25:
        level, label = "low", "credible"
    elif score <= 45:
        level, label = "medium", "needs_context"
    elif score <= 65:
        level, label = "high", "suspicious"
    else:
        level, label = "critical", "likely_misinformation"

    if score_log_enabled:
        logger.info(
            "报告计分结果：risk_score=%s risk_level=%s risk_label=%s suspicious_points=%s",
            score,
            level,
            label,
            len(suspicious_points),
        )

    scenario = "general"
    if claims:
        text_for_scenario = " ".join(claim.claim_text for claim in claims[:3])
        scenario = detect_scenario(text_for_scenario)

    domain_set: set[str] = set()
    for evidence in evidences:
        if evidence.domain:
            domain_set.add(evidence.domain)

    # 尝试 LLM 报告生成
    llm_report = generate_report_with_llm(
        original_text=original_text,
        claims=claims,
        evidence_alignments=claim_reports,
        risk_score=score,
        scenario=scenario,
    )

    if llm_report:
        # 使用 LLM 生成的内容
        summary = llm_report.get("summary", "")
        llm_suspicious = llm_report.get("suspicious_points", [])
        claim_conclusions = llm_report.get("claim_conclusions", {})
        risk_reasoning = llm_report.get("risk_reasoning", "")

        # 合并 LLM 可疑点和规则可疑点
        final_suspicious = llm_suspicious if llm_suspicious else suspicious_points

        # 更新 claim_reports 的 notes
        for cr in claim_reports:
            claim_obj = cr.get("claim")
            claim_id = claim_obj.claim_id if claim_obj else ""
            if claim_id in claim_conclusions and claim_conclusions[claim_id]:
                existing_notes = cr.get("notes", [])
                cr["notes"] = [claim_conclusions[claim_id]] + existing_notes

        # 如果有风险理由，添加到摘要
        if risk_reasoning and summary:
            summary = f"{summary} {risk_reasoning}"

        return {
            "risk_score": score,
            "risk_level": level,
            "risk_label": label,
            "detected_scenario": scenario,
            "evidence_domains": sorted(domain_set),
            "source_url": source_url,
            "source_title": source_title,
            "source_publish_date": source_publish_date,
            "summary": summary
            or f"已处理 {len(claims)} 条主张，匹配 {len(evidences)} 条证据。",
            "suspicious_points": final_suspicious
            or ["暂未发现关键矛盾点，建议持续监测。"],
            "claim_reports": claim_reports,
        }

    # 规则兜底
    fallback = generate_fallback_report(
        claims=claims,
        evidence_alignments=claim_reports,
        risk_score=score,
    )

    return {
        "risk_score": score,
        "risk_level": level,
        "risk_label": label,
        "detected_scenario": scenario,
        "evidence_domains": sorted(domain_set),
        "source_url": source_url,
        "source_title": source_title,
        "source_publish_date": source_publish_date,
        "summary": fallback.get(
            "summary", f"已处理 {len(claims)} 条主张，匹配 {len(evidences)} 条证据。"
        ),
        "suspicious_points": fallback.get("suspicious_points", suspicious_points)
        or ["暂未发现关键矛盾点，建议持续监测。"],
        "claim_reports": claim_reports,
    }


def _process_claims_parallel(
    claim_inputs: list[tuple[ClaimItem, list[EvidenceItem]]],
    strategy: StrategyConfig | None = None,
) -> list[dict]:
    workers = _int_env("TRUTHCAST_CLAIM_PARALLEL_WORKERS", 3)
    if workers <= 1 or len(claim_inputs) <= 1:
        return [
            _process_one_claim(claim, related, strategy=strategy)
            for claim, related in claim_inputs
        ]

    with ThreadPoolExecutor(max_workers=workers) as executor:
        return list(
            executor.map(
                lambda row: _process_one_claim(row[0], row[1], strategy=strategy),
                claim_inputs,
            )
        )


def _process_one_claim(
    claim: ClaimItem,
    related: list[EvidenceItem],
    strategy: StrategyConfig | None = None,
) -> dict:
    summarized = summarize_evidence_for_claim(
        claim.claim_text, related, strategy=strategy
    )
    if not summarized:
        return {
            "claim": claim,
            "evidences": [],
            "final_stance": "insufficient",
            "notes": ["需要人工复核"],
            "suspicious_point": f"{claim.claim_id} 未找到可用证据",
            "score_delta": -8,
        }

    aligned_items = _align_evidences_parallel(claim.claim_text, summarized)
    weighted = {"support": 0.0, "refute": 0.0, "insufficient": 0.0}
    rationales: list[str] = []

    for item in aligned_items:
        confidence = (
            item.alignment_confidence if item.alignment_confidence is not None else 0.5
        )
        weighted[item.stance] = weighted.get(item.stance, 0.0) + (
            item.source_weight * max(0.2, confidence)
        )
        if item.alignment_rationale:
            rationales.append(item.alignment_rationale)

    stance = max(weighted, key=lambda k: weighted[k])
    notes = [f"主立场：{stance}", f"证据数量：{len(aligned_items)}"]
    if rationales:
        notes.append(f"对齐结论：{rationales[0]}")

    if stance == "refute":
        score_delta = -12
        suspicious_point = f"{claim.claim_id} 被证据反驳"
    elif stance == "support":
        score_delta = 6
        suspicious_point = ""
    else:
        score_delta = -4
        suspicious_point = f"{claim.claim_id} 证据不足以形成明确支持"

    return {
        "claim": claim,
        "evidences": aligned_items,
        "final_stance": stance,
        "notes": notes,
        "suspicious_point": suspicious_point,
        "score_delta": score_delta,
    }


def _align_evidences_parallel(
    claim_text: str, evidences: list[EvidenceItem]
) -> list[EvidenceItem]:
    workers = _int_env("TRUTHCAST_ALIGN_PARALLEL_WORKERS", 4)
    if workers <= 1 or len(evidences) <= 1:
        return [_align_one_evidence(claim_text, item) for item in evidences]

    with ThreadPoolExecutor(max_workers=workers) as executor:
        return list(
            executor.map(lambda item: _align_one_evidence(claim_text, item), evidences)
        )


def align_evidences(
    claims: list[ClaimItem],
    evidences: list[EvidenceItem],
    strategy: StrategyConfig | None = None,
) -> list[EvidenceItem]:
    """
    证据聚合与对齐

    对每条主张的证据执行：
    1. 证据聚合（多条检索证据 → 少量摘要证据）
    2. 证据对齐（每条摘要证据与主张对齐）

    Args:
        claims: 主张列表
        evidences: 检索到的原始证据
        strategy: 策略配置

    Returns:
        对齐后的证据列表
    """
    by_claim: dict[str, list[EvidenceItem]] = defaultdict(list)
    for item in evidences:
        by_claim[item.claim_id].append(item)

    aligned_evidences: list[EvidenceItem] = []

    for claim in claims:
        related = by_claim.get(claim.claim_id, [])
        if not related:
            continue

        # Step 1: 证据聚合
        summarized = summarize_evidence_for_claim(
            claim.claim_text, related, strategy=strategy
        )
        if not summarized:
            continue

        # Step 2: 证据对齐
        aligned_items = _align_evidences_parallel(claim.claim_text, summarized)
        aligned_evidences.extend(aligned_items)

    return aligned_evidences


def _align_one_evidence(claim_text: str, item: EvidenceItem) -> EvidenceItem:
    aligned = align_claim_with_evidence(claim_text, item)
    item.stance = aligned.stance
    item.alignment_confidence = aligned.confidence
    item.alignment_rationale = aligned.rationale
    return item


def _int_env(key: str, default: int) -> int:
    raw = os.getenv(key, str(default)).strip()
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(1, value)


def _float_env(key: str, default: float, min_value: float, max_value: float) -> float:
    raw = os.getenv(key, str(default)).strip()
    try:
        value = float(raw)
    except ValueError:
        value = default
    if value < min_value:
        return min_value
    if value > max_value:
        return max_value
    return value


def _weighted_delta(base_delta: int, factor: float) -> int:
    weighted = int(round(base_delta * factor))
    if base_delta != 0 and weighted == 0:
        return 1 if base_delta > 0 else -1
    return weighted


def _report_score_log_enabled() -> bool:
    specific = os.getenv("TRUTHCAST_REPORT_SCORE_BREAKDOWN_ENABLED", "").strip().lower()
    if specific in {"true", "false"}:
        return specific == "true"
    return os.getenv("TRUTHCAST_DEBUG_REPORT", "false").strip().lower() == "true"


def simulate_opinion(
    text: str,
    time_window_hours: int = 24,
    platform: str = "general",
    comments: list[str] | None = None,
    claims: list[ClaimItem] | None = None,
    evidences: list[EvidenceItem] | None = None,
    report: ReportResponse | None = None,
) -> SimulateResponse:
    """
    舆情预演入口（LLM 驱动 + 规则兜底）

    Args:
        text: 待传播文本
        time_window_hours: 预演时间窗口
        platform: 传播平台
        comments: 已有评论样本
        claims: 已提取的主张列表
        evidences: 已检索的证据列表
        report: 已生成的风险报告

    Returns:
        SimulateResponse: 完整的舆情预演结果
    """
    return simulate_opinion_with_llm(
        text=text,
        claims=claims,
        evidences=evidences,
        report=report,
        time_window_hours=time_window_hours,
        platform=platform,
        comments=comments,
    )
