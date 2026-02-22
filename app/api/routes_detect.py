import os

from fastapi import APIRouter

from app.core.cache import claims_cache, detect_cache
from app.core.concurrency import llm_slot
from app.core.logger import get_logger
from app.orchestrator import orchestrator
from app.schemas.detect import (
    ClaimsRequest,
    ClaimsResponse,
    DetectRequest,
    DetectResponse,
    EvidenceAlignRequest,
    EvidenceAlignResponse,
    EvidenceRequest,
    EvidenceResponse,
    ReportRequest,
    ReportResponse,
    StrategyConfig,
)
from app.services.history_store import save_report
from app.services.pipeline import align_evidences
from app.services.risk_snapshot import detect_risk_snapshot

router = APIRouter(prefix="/detect", tags=["detect"])
logger = get_logger("truthcast.routes_detect")

_DEFAULT_MAX_CHARS = 8000

# 在模块加载时读取一次，避免每个请求重复调用 os.getenv
try:
    _MAX_INPUT_CHARS: int = int(os.getenv("TRUTHCAST_MAX_INPUT_CHARS", _DEFAULT_MAX_CHARS))
except (ValueError, TypeError):
    _MAX_INPUT_CHARS = _DEFAULT_MAX_CHARS


def _truncate_text(text: str) -> tuple[str, bool]:
    """若文本超过限制，截断并返回 (truncated_text, was_truncated)"""
    limit = _MAX_INPUT_CHARS
    if len(text) <= limit:
        return text, False
    logger.warning("输入文本超过 %d 字符（实际 %d），已自动截断", limit, len(text))
    return text[:limit], True


@router.post("", response_model=DetectResponse)
def detect_fake_news(payload: DetectRequest) -> DetectResponse:
    text, truncated = _truncate_text(payload.text)

    # 缓存命中，直接返回（截断状态由本次请求决定，无需消耗 LLM 槽位）
    cached = detect_cache.get(text)
    if cached is not None:
        logger.info("风险快照：缓存命中，跳过 LLM 调用")
        return cached.model_copy(update={"truncated": truncated})

    with llm_slot():
        result = detect_risk_snapshot(text)
    resp = DetectResponse(
        label=result.label,
        confidence=result.confidence,
        score=result.score,
        reasons=result.reasons,
        strategy=result.strategy,
        truncated=truncated,
    )
    detect_cache.set(text, resp)
    return resp


@router.post("/claims", response_model=ClaimsResponse)
def detect_claims(payload: ClaimsRequest) -> ClaimsResponse:
    text, _ = _truncate_text(payload.text)

    # 缓存命中（仅当未指定自定义策略时缓存，避免策略不同导致误命中）
    if payload.strategy is None:
        cached = claims_cache.get(text)
        if cached is not None:
            logger.info("主张抽取：缓存命中，跳过 LLM 调用")
            return cached

    with llm_slot():
        result = ClaimsResponse(claims=orchestrator.run_claims(text, strategy=payload.strategy))

    if payload.strategy is None:
        claims_cache.set(text, result)

    return result


@router.post("/evidence", response_model=EvidenceResponse)
def detect_evidence(payload: EvidenceRequest) -> EvidenceResponse:
    text = payload.text
    if text:
        text, _ = _truncate_text(text)
    with llm_slot():
        evidences = orchestrator.run_evidence(text=text, claims=payload.claims, strategy=payload.strategy)
    return EvidenceResponse(evidences=evidences)


@router.post("/evidence/align", response_model=EvidenceAlignResponse)
def align_evidence(payload: EvidenceAlignRequest) -> EvidenceAlignResponse:
    """
    证据聚合与对齐

    对每条主张的证据执行：
    1. 证据聚合（多条检索证据 → 少量摘要证据）
    2. 证据对齐（每条摘要证据与主张对齐）
    """
    with llm_slot():
        aligned = align_evidences(
            claims=payload.claims,
            evidences=payload.evidences,
            strategy=payload.strategy,
        )
    return EvidenceAlignResponse(evidences=aligned)


@router.post("/report")
def detect_report(payload: ReportRequest) -> dict:
    text = payload.text
    if text:
        text, _ = _truncate_text(text)

    with llm_slot():
        report = orchestrator.run_report(
            text=text, claims=payload.claims, evidences=payload.evidences, strategy=payload.strategy
        )
    input_text = text or " ".join((item.claim_text for item in (payload.claims or []))) or "[无原文]"

    detect_data = None
    if payload.detect_data:
        detect_data = {
            "label": payload.detect_data.label,
            "confidence": payload.detect_data.confidence,
            "score": payload.detect_data.score,
            "reasons": payload.detect_data.reasons,
        }

    record_id = save_report(
        input_text=input_text,
        report=report,
        detect_data=detect_data,
    )

    return {"record_id": record_id, **report}
