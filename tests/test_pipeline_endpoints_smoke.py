from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_claims_endpoint() -> None:
    response = client.post(
        "/detect/claims",
        json={"text": "Official statement says infection rate is 3% on 2026-02-09."},
    )
    body = response.json()
    assert response.status_code == 200
    assert "claims" in body
    assert len(body["claims"]) >= 1


def test_evidence_endpoint() -> None:
    response = client.post(
        "/detect/evidence",
        json={"text": "Shocking internal source says this is 100% true."},
    )
    body = response.json()
    assert response.status_code == 200
    assert "evidences" in body
    assert len(body["evidences"]) >= 1


def test_report_endpoint() -> None:
    response = client.post(
        "/detect/report",
        json={"text": "Shocking post claims miracle cure with no source."},
    )
    body = response.json()
    assert response.status_code == 200
    assert "risk_score" in body
    assert "claim_reports" in body
    assert "detected_scenario" in body
    assert "evidence_domains" in body
    first_claim = body["claim_reports"][0]
    assert "notes" in first_claim
    if first_claim["evidences"]:
        first_evidence = first_claim["evidences"][0]
        assert "alignment_rationale" in first_evidence
        assert "alignment_confidence" in first_evidence


def test_report_endpoint_with_source_meta() -> None:
    response = client.post(
        "/detect/report",
        json={
            "text": "某链接新闻称出现异常情况。",
            "source_url": "https://example.com/news/1",
            "source_title": "示例新闻标题",
            "source_publish_date": "2026-03-03",
        },
    )
    body = response.json()
    assert response.status_code == 200
    assert body["source_url"] == "https://example.com/news/1"
    assert body["source_title"] == "示例新闻标题"
    assert body["source_publish_date"] == "2026-03-03"


def test_simulate_endpoint() -> None:
    response = client.post(
        "/simulate",
        json={
            "text": "Shocking rumor is spreading rapidly.",
            "time_window_hours": 24,
            "platform": "weibo",
        },
    )
    body = response.json()
    assert response.status_code == 200
    assert "narratives" in body
    assert len(body["narratives"]) >= 2
