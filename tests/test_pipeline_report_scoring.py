from app.schemas.detect import ClaimItem, EvidenceItem
from app.services import pipeline


def _claim(claim_id: str, text: str) -> ClaimItem:
    return ClaimItem(
        claim_id=claim_id,
        claim_text=text,
        source_sentence=text,
    )


def _evidence(evidence_id: str, claim_id: str, stance: str) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        claim_id=claim_id,
        title="样例证据",
        source="样例来源",
        url="https://example.com",
        published_at="2026-02-28",
        summary="样例摘要",
        stance=stance,
        source_weight=1.0,
        source_type="web_live",
        alignment_confidence=1.0,
        alignment_rationale="样例对齐",
    )


def test_build_report_rank_weight_affects_score(monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_CLAIM_RANK_ALPHA", "1.0")
    monkeypatch.setenv("TRUTHCAST_REPORT_TOPK", "0")
    monkeypatch.setenv("TRUTHCAST_REPORT_NON_TOPK_FACTOR", "1.0")
    monkeypatch.setattr(pipeline, "generate_report_with_llm", lambda **kwargs: None)

    claims = [_claim("c1", "主张1"), _claim("c2", "主张2")]
    evidences = [_evidence("e1", "c1", "refute"), _evidence("e2", "c2", "refute")]

    report = pipeline.build_report(
        claims=claims, evidences=evidences, original_text="text"
    )
    assert report["risk_score"] == 63


def test_build_report_topk_discount_affects_score(monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_CLAIM_RANK_ALPHA", "0")
    monkeypatch.setenv("TRUTHCAST_REPORT_TOPK", "1")
    monkeypatch.setenv("TRUTHCAST_REPORT_NON_TOPK_FACTOR", "0.25")
    monkeypatch.setattr(pipeline, "generate_report_with_llm", lambda **kwargs: None)

    claims = [_claim("c1", "主张1"), _claim("c2", "主张2")]
    evidences = [_evidence("e1", "c1", "refute"), _evidence("e2", "c2", "refute")]

    report = pipeline.build_report(
        claims=claims, evidences=evidences, original_text="text"
    )
    assert report["risk_score"] == 60
