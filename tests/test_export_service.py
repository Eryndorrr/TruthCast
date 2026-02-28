from io import BytesIO
from zipfile import ZipFile

from app.schemas.export import ExportDataRequest
from app.services.export_service import _build_html, generate_word_bytes


def _sample_export_data() -> ExportDataRequest:
    return ExportDataRequest.model_validate(
        {
            "inputText": "示例新闻文本",
            "detectData": {
                "label": "high_risk",
                "confidence": 0.82,
                "score": 32,
                "reasons": ["样例理由1", "样例理由2"],
                "strategy": None,
                "truncated": False,
            },
            "claims": [
                {
                    "claim_id": "c1",
                    "claim_text": "某地明天全市停课",
                    "source_sentence": "网传某地明天全市停课",
                }
            ],
            "evidences": [
                {
                    "evidence_id": "e1",
                    "claim_id": "c1",
                    "title": "教育局辟谣",
                    "source": "市教育局",
                    "url": "https://example.com/1",
                    "published_at": "2026-02-28",
                    "summary": "官方表示不停课",
                    "stance": "refute",
                    "source_weight": 0.9,
                    "source_type": "web_live",
                    "domain": "education",
                    "alignment_rationale": "与停课主张冲突",
                    "alignment_confidence": 0.88,
                }
            ],
            "report": {
                "risk_score": 34,
                "risk_level": "high",
                "risk_label": "high_risk",
                "detected_scenario": "education",
                "evidence_domains": ["education", "media"],
                "summary": "存在明显误导风险",
                "suspicious_points": ["主张与官方公告矛盾"],
                "claim_reports": [
                    {
                        "claim": {
                            "claim_id": "c1",
                            "claim_text": "某地明天全市停课",
                            "source_sentence": "网传某地明天全市停课",
                        },
                        "evidences": [
                            {
                                "evidence_id": "e1",
                                "claim_id": "c1",
                                "title": "教育局辟谣",
                                "source": "市教育局",
                                "url": "https://example.com/1",
                                "published_at": "2026-02-28",
                                "summary": "官方表示不停课",
                                "stance": "refute",
                                "source_weight": 0.9,
                                "source_type": "web_live",
                                "domain": "education",
                                "alignment_rationale": "与停课主张冲突",
                                "alignment_confidence": 0.88,
                            }
                        ],
                        "final_stance": "refute",
                        "notes": ["建议关注官方渠道"],
                    }
                ],
            },
            "simulation": {
                "emotion_distribution": {"anger": 0.4, "fear": 0.6},
                "stance_distribution": {"supportive": 0.2, "opposing": 0.8},
                "narratives": [
                    {
                        "title": "官方辟谣扩散",
                        "stance": "opposing",
                        "probability": 0.7,
                        "trigger_keywords": ["停课", "辟谣"],
                        "sample_message": "教育局已辟谣，请勿传播",
                    }
                ],
                "flashpoints": ["微信群扩散"],
                "suggestion": {
                    "summary": "尽快发布澄清",
                    "actions": [
                        {
                            "priority": "urgent",
                            "category": "official",
                            "action": "发布公告并置顶",
                            "timeline": "1小时内",
                            "responsible": "教育局",
                        }
                    ],
                },
                "timeline": [
                    {"hour": 1, "event": "谣言扩散", "expected_reach": "10万"}
                ],
                "emotion_drivers": ["恐慌"],
                "stance_drivers": ["官方澄清"],
            },
            "content": None,
            "exportedAt": "2026-02-28T00:00:00Z",
        }
    )


def test_build_html_claim_columns_are_simplified() -> None:
    html = _build_html(_sample_export_data())
    assert "<th>ID</th><th>主张内容</th>" in html
    assert "<th>ID</th><th>主张内容</th><th>实体</th>" not in html
    assert "<th>ID</th><th>主张内容</th><th>时间</th>" not in html
    assert "<th>ID</th><th>主张内容</th><th>地点</th>" not in html


def test_build_html_contains_evidence_chain_and_simulation_sections() -> None:
    html = _build_html(_sample_export_data())
    assert "<h2>证据链</h2>" in html
    assert "<h3>情绪分布</h3>" in html
    assert "<h3>立场分布</h3>" in html
    assert "<h3>叙事分支</h3>" in html
    assert "<h3>时间线</h3>" in html
    assert "<h3>应对建议</h3>" in html


def test_build_html_maps_report_domains_to_chinese() -> None:
    html = _build_html(_sample_export_data())
    assert "证据覆盖域" in html
    assert "教育校园、媒体传播" in html


def test_build_html_maps_claim_and_narrative_stance_to_chinese() -> None:
    html = _build_html(_sample_export_data())
    assert "<strong>最终立场：</strong>反驳" in html
    assert "<strong>立场：</strong>反对" in html


def test_generate_word_bytes_contains_zh_font_config() -> None:
    data = _sample_export_data()
    content = generate_word_bytes(data)
    with ZipFile(BytesIO(content), "r") as zf:
        styles_xml = zf.read("word/styles.xml").decode("utf-8", errors="ignore")
    assert 'w:eastAsia="Microsoft YaHei"' in styles_xml
