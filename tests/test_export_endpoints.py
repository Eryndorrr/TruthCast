from fastapi.testclient import TestClient

from app.main import app
import app.api.routes_export as routes_export


def _sample_payload() -> dict:
    return {
        "inputText": "这是一段待核查文本。",
        "detectData": {
            "label": "suspicious",
            "confidence": 0.75,
            "score": 62,
            "reasons": ["样例原因"],
            "strategy": None,
            "truncated": False,
        },
        "claims": [],
        "evidences": [],
        "report": None,
        "simulation": None,
        "content": None,
        "exportedAt": "2026-02-28T00:00:00Z",
    }


def test_export_pdf_ok(monkeypatch) -> None:
    monkeypatch.setattr(
        routes_export, "generate_pdf_bytes", lambda _data: b"%PDF-1.4 sample"
    )
    client = TestClient(app)
    response = client.post("/export/pdf", json=_sample_payload())
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")
    assert "attachment; filename=" in response.headers.get("content-disposition", "")
    assert response.content.startswith(b"%PDF")


def test_export_word_ok(monkeypatch) -> None:
    monkeypatch.setattr(
        routes_export, "generate_word_bytes", lambda _data: b"PK\x03\x04"
    )
    client = TestClient(app)
    response = client.post("/export/word", json=_sample_payload())
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert "attachment; filename=" in response.headers.get("content-disposition", "")
    assert response.content.startswith(b"PK")


def test_export_pdf_dependency_error(monkeypatch) -> None:
    def _raise(_data):
        raise RuntimeError("PDF 导出依赖未安装")

    monkeypatch.setattr(routes_export, "generate_pdf_bytes", _raise)
    client = TestClient(app)
    response = client.post("/export/pdf", json=_sample_payload())
    assert response.status_code == 500
    assert response.json()["detail"] == "PDF 导出依赖未安装"


def test_export_pdf_unexpected_error(monkeypatch) -> None:
    def _raise(_data):
        raise ValueError("boom")

    monkeypatch.setattr(routes_export, "generate_pdf_bytes", _raise)
    client = TestClient(app)
    response = client.post("/export/pdf", json=_sample_payload())
    assert response.status_code == 500
    assert response.json()["detail"].startswith("PDF 导出失败：")
