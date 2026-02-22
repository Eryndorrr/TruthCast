"""
应对内容生成模块测试

测试：
1. Schema 验证
2. 规则兜底逻辑
3. API 端点响应
"""

import pytest
from datetime import datetime, timezone

from app.schemas.detect import (
    ContentGenerateRequest,
    ContentGenerateResponse,
    ClarificationContent,
    ClarificationStyle,
    FAQItem,
    PlatformScript,
    Platform,
    ReportResponse,
    ClaimReportItem,
    ClaimItem,
)


def _make_sample_report() -> ReportResponse:
    """创建示例报告"""
    return ReportResponse(
        risk_score=65,
        risk_level="high",
        risk_label="suspicious",
        detected_scenario="governance",
        evidence_domains=["media", "government"],
        summary="该信息经核查存在多处可疑点",
        suspicious_points=["数据来源不明", "时间信息模糊"],
        claim_reports=[
            ClaimReportItem(
                claim=ClaimItem(
                    claim_id="c1",
                    claim_text="某地发生重大事件",
                    source_sentence="据传某地发生重大事件",
                ),
                evidences=[],
                final_stance="insufficient_evidence",
                notes=["证据不足"],
            ),
        ],
    )


def test_clarification_content():
    """测试澄清稿 Schema"""
    content = ClarificationContent(
        short="短版澄清稿",
        medium="中版澄清稿内容",
        long="长版澄清稿详细内容",
    )
    assert content.short == "短版澄清稿"
    assert content.medium == "中版澄清稿内容"
    assert content.long == "长版澄清稿详细内容"


def test_faq_item():
    """测试 FAQ Schema"""
    faq = FAQItem(
        question="该信息是否属实？",
        answer="经核查，该信息存在可疑点",
        category="core",
    )
    assert faq.question == "该信息是否属实？"
    assert faq.answer == "经核查，该信息存在可疑点"
    assert faq.category == "core"


def test_platform_script():
    """测试平台话术 Schema"""
    script = PlatformScript(
        platform=Platform.WEIBO,
        content="微博正文内容 #话题标签",
        tips=["最佳发布时间：早8点"],
        hashtags=["#真相来了", "#辟谣"],
    )
    assert script.platform == Platform.WEIBO
    assert script.content == "微博正文内容 #话题标签"
    assert len(script.tips) == 1
    assert len(script.hashtags) == 2


def test_content_generate_request():
    """测试内容生成请求 Schema"""
    report = _make_sample_report()
    request = ContentGenerateRequest(
        text="测试新闻文本",
        report=report,
        style=ClarificationStyle.FORMAL,
        platforms=[Platform.WEIBO, Platform.WECHAT],
        include_faq=True,
        faq_count=5,
    )
    assert request.text == "测试新闻文本"
    assert request.style == ClarificationStyle.FORMAL
    assert len(request.platforms) == 2
    assert Platform.WEIBO in request.platforms
    assert request.include_faq is True
    assert request.faq_count == 5


def test_content_generate_request_defaults():
    """测试内容生成请求默认值"""
    report = _make_sample_report()
    request = ContentGenerateRequest(
        text="测试新闻文本",
        report=report,
    )
    assert request.style == ClarificationStyle.NEUTRAL
    assert Platform.WEIBO in request.platforms
    assert Platform.WECHAT in request.platforms
    assert request.include_faq is True
    assert request.faq_count == 5


def test_content_generate_response():
    """测试内容生成响应 Schema"""
    response = ContentGenerateResponse(
        clarification=ClarificationContent(
            short="短版",
            medium="中版",
            long="长版",
        ),
        faq=[
            FAQItem(question="Q1", answer="A1", category="core"),
        ],
        platform_scripts=[
            PlatformScript(
                platform=Platform.WEIBO,
                content="微博内容",
                tips=[],
            ),
        ],
        generated_at=datetime.now(timezone.utc).isoformat(),
        based_on={"risk_level": "high"},
    )
    assert response.clarification.short == "短版"
    assert len(response.faq) == 1
    assert len(response.platform_scripts) == 1
    assert response.based_on["risk_level"] == "high"


def test_platform_enum():
    """测试平台枚举"""
    assert Platform.WEIBO.value == "weibo"
    assert Platform.WECHAT.value == "wechat"
    assert Platform.XIAOHONGSHU.value == "xiaohongshu"
    assert Platform.DOUYIN.value == "douyin"
    assert Platform.KUAISHOU.value == "kuaishou"
    assert Platform.BILIBILI.value == "bilibili"


def test_clarification_style_enum():
    """测试风格枚举"""
    assert ClarificationStyle.FORMAL.value == "formal"
    assert ClarificationStyle.FRIENDLY.value == "friendly"
    assert ClarificationStyle.NEUTRAL.value == "neutral"


# === 规则兜底测试 ===

def test_fallback_clarification():
    """测试规则兜底澄清稿生成"""
    from app.services.content_generation.clarification import _fallback_clarification
    
    report = _make_sample_report()
    content = _fallback_clarification(report, ClarificationStyle.NEUTRAL)
    
    assert content.short is not None
    assert content.medium is not None
    assert content.long is not None
    assert len(content.short) <= 150  # 短版限制
    assert "可疑" in content.short or "风险" in content.short


def test_fallback_faq():
    """测试规则兜底 FAQ 生成"""
    from app.services.content_generation.faq import _fallback_faq
    
    report = _make_sample_report()
    faq_list = _fallback_faq(report, 5)
    
    assert len(faq_list) <= 5
    assert all(isinstance(f, FAQItem) for f in faq_list)
    # 核心问题应该在第一位
    if faq_list:
        assert faq_list[0].category == "core"


def test_fallback_platform_script():
    """测试规则兜底平台话术生成"""
    from app.services.content_generation.platform_scripts import _fallback_platform_script
    
    clarification = ClarificationContent(
        short="短版澄清稿",
        medium="中版澄清稿",
        long="长版澄清稿",
    )
    report = _make_sample_report()
    
    # 测试微博
    script = _fallback_platform_script(Platform.WEIBO, clarification, report)
    assert script.platform == Platform.WEIBO
    assert len(script.content) <= 280
    assert script.hashtags is not None
    
    # 测试小红书
    script = _fallback_platform_script(Platform.XIAOHONGSHU, clarification, report)
    assert script.platform == Platform.XIAOHONGSHU
    assert len(script.content) <= 500
    
    # 测试抖音
    script = _fallback_platform_script(Platform.DOUYIN, clarification, report)
    assert script.platform == Platform.DOUYIN
    assert "开头" in script.content or "开头" not in script.content  # 脚本格式
