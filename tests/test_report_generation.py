"""
Tests for report_generation module
"""

import os
import pytest

os.environ["TRUTHCAST_REPORT_LLM_ENABLED"] = "false"
os.environ["TRUTHCAST_DEBUG_REPORT"] = "false"

from app.schemas.detect import ClaimItem
from app.services.report_generation import (
    REPORT_LLM_ENABLED,
    _build_claim_evidence_summary,
    _get_current_time_context,
    _normalize_llm_output,
    generate_fallback_report,
    generate_report_with_llm,
)


def make_claim(claim_id: str, claim_text: str) -> ClaimItem:
    return ClaimItem(
        claim_id=claim_id,
        claim_text=claim_text,
        entity=None,
        time=None,
        location=None,
        value=None,
        source_sentence=claim_text,
    )


class TestGetCurentTimeContext:
    def test_returns_formatted_string(self):
        result = _get_current_time_context()
        assert "UTC" in result
        assert len(result) > 10


class TestBuildClaimEvidenceSummary:
    def test_empty_claims(self):
        result = _build_claim_evidence_summary([], [])
        assert result == ""

    def test_single_claim_no_evidence(self):
        claim = make_claim("c1", "测试主张内容")
        alignment = {"final_stance": "insufficient", "notes": [], "evidences": []}
        result = _build_claim_evidence_summary([claim], [alignment])
        assert "c1" in result
        assert "测试主张内容" in result

    def test_multiple_claims(self):
        claims = [
            make_claim("c1", "主张一"),
            make_claim("c2", "主张二"),
        ]
        alignments = [
            {"final_stance": "support", "notes": ["支持"], "evidences": []},
            {"final_stance": "refute", "notes": ["反驳"], "evidences": []},
        ]
        result = _build_claim_evidence_summary(claims, alignments)
        assert "c1" in result
        assert "c2" in result


class TestNormalizeLlmOutput:
    def test_basic_normalization(self):
        parsed = {
            "summary": "测试摘要",
            "suspicious_points": ["可疑点1", "可疑点2"],
            "claim_conclusions": [{"claim_id": "c1", "conclusion": "结论1"}],
            "risk_reasoning": "风险理由",
        }
        claims = [make_claim("c1", "主张"), make_claim("c2", "主张2")]
        result = _normalize_llm_output(parsed, claims)
        
        assert result["summary"] == "测试摘要"
        assert len(result["suspicious_points"]) == 2
        assert result["claim_conclusions"]["c1"] == "结论1"
        assert result["claim_conclusions"]["c2"] == ""  # 默认填充
        assert result["risk_reasoning"] == "风险理由"

    def test_missing_fields(self):
        parsed = {}
        claims = [make_claim("c1", "主张")]
        result = _normalize_llm_output(parsed, claims)
        
        assert result["summary"] == ""
        assert result["suspicious_points"] == []
        assert result["claim_conclusions"]["c1"] == ""
        assert result["risk_reasoning"] == ""


class TestGenerateFallbackReport:
    def test_high_risk_score(self):
        claims = [make_claim("c1", "高风险主张")]
        alignments = [{"claim": claims[0], "final_stance": "refute", "notes": [], "evidences": []}]
        result = generate_fallback_report(claims, alignments, risk_score=20)
        
        assert "较高风险" in result["summary"]
        assert "c1 被证据直接反驳" in result["suspicious_points"]
        assert result["claim_conclusions"]["c1"] == "该主张与证据存在矛盾，建议谨慎采信。"

    def test_medium_risk_score(self):
        claims = [make_claim("c1", "中等风险主张")]
        alignments = [{"claim": claims[0], "final_stance": "insufficient", "notes": [], "evidences": []}]
        result = generate_fallback_report(claims, alignments, risk_score=50)
        
        # risk_score=50 falls in [35, 55) range → "可疑之处"
        assert "可疑" in result["summary"] or "补充语境" in result["summary"]

    def test_low_risk_score(self):
        claims = [make_claim("c1", "低风险主张")]
        alignments = [{"claim": claims[0], "final_stance": "support", "notes": [], "evidences": []}]
        result = generate_fallback_report(claims, alignments, risk_score=80)
        
        assert "可信度较高" in result["summary"]

    def test_no_suspicious_points(self):
        claims = [make_claim("c1", "主张")]
        alignments = [{"claim": claims[0], "final_stance": "support", "notes": [], "evidences": []}]
        result = generate_fallback_report(claims, alignments, risk_score=80)
        
        assert "暂未发现明显矛盾点" in result["suspicious_points"][0]


class TestGenerateReportWithLlm:
    def test_llm_disabled(self):
        # 模块顶层已通过 os.environ 设置 TRUTHCAST_REPORT_LLM_ENABLED=false
        # 但如果 .env 中配置了 API key 且启用了 LLM，则可能返回非 None
        result = generate_report_with_llm(
            original_text="测试文本",
            claims=[make_claim("c1", "主张")],
            evidence_alignments=[],
            risk_score=50,
            scenario="general",
        )
        if REPORT_LLM_ENABLED:
            # LLM 已启用（来自环境），验证返回结构
            assert isinstance(result, dict)
        else:
            assert result is None


def test_report_prompt_contains_time_rules(monkeypatch):
    """仅验证 prompt 文案包含时间硬规则与自检，不依赖真实 LLM。"""
    from app.services import report_generation

    monkeypatch.setattr(report_generation, "REPORT_LLM_ENABLED", True)
    monkeypatch.setattr(report_generation, "REPORT_LLM_API_KEY", "dummy")
    monkeypatch.setattr(report_generation, "REPORT_LLM_BASE_URL", "https://example.invalid")
    monkeypatch.setattr(report_generation, "REPORT_LLM_MODEL", "dummy-model")
    monkeypatch.setattr(report_generation, "DEBUG_REPORT", False)

    captured = {}

    class DummyResp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"summary":"ok","suspicious_points":[],"claim_conclusions":[],"risk_reasoning":""}'
                            )
                        }
                    }
                ]
            }

    class DummyClient:
        def __init__(self, timeout=None):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, headers=None, json=None):
            captured["url"] = url
            captured["payload"] = json
            return DummyResp()

    monkeypatch.setattr(report_generation.httpx, "Client", DummyClient)

    c1 = make_claim("c1", "2026年2月22日发布一则新闻")
    result = report_generation.generate_report_with_llm(
        original_text="2026年2月22日，某地发布消息。",
        claims=[c1],
        evidence_alignments=[{"final_stance": "insufficient", "notes": [], "evidences": []}],
        risk_score=50,
        scenario="general",
    )
    assert isinstance(result, dict)

    messages = captured["payload"]["messages"]
    user_prompt = messages[1]["content"]
    assert "【时间判断硬规则（必须遵守）】" in user_prompt
    assert "runtime_date_local" in user_prompt
    assert "【自检】" in user_prompt
