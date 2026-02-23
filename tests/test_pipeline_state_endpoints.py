import time

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_pipeline_state_save_and_load_latest() -> None:
    task_id = f"test_task_{int(time.time())}"
    phases = {
        "detect": "running",
        "claims": "idle",
        "evidence": "idle",
        "report": "idle",
        "simulation": "idle",
        "content": "idle",
    }

    save_resp = client.post(
        "/pipeline/save-phase",
        json={
            "task_id": task_id,
            "input_text": "测试：阶段持久化",
            "phases": phases,
            "phase": "detect",
            "status": "running",
            "duration_ms": None,
            "error_message": None,
            "payload": {"detectData": {"risk_label": "可信", "risk_score": 10}},
            "meta": {"recordId": "r_test"},
        },
    )
    assert save_resp.status_code == 200

    # update same phase to done (UPSERT)
    phases["detect"] = "done"
    save_resp2 = client.post(
        "/pipeline/save-phase",
        json={
            "task_id": task_id,
            "input_text": "测试：阶段持久化",
            "phases": phases,
            "phase": "detect",
            "status": "done",
            "duration_ms": 123,
            "error_message": None,
            "payload": {"detectData": {"risk_label": "可信", "risk_score": 10}},
            "meta": {"recordId": "r_test"},
        },
    )
    assert save_resp2.status_code == 200

    latest_resp = client.get("/pipeline/load-latest")
    assert latest_resp.status_code == 200
    body = latest_resp.json()

    assert body["task_id"] == task_id
    assert body["input_text"] == "测试：阶段持久化"
    assert body["phases"]["detect"] == "done"
    assert isinstance(body.get("snapshots"), list)

    snap_detect = [s for s in body["snapshots"] if s["phase"] == "detect"]
    assert len(snap_detect) == 1
    assert snap_detect[0]["status"] == "done"
    assert snap_detect[0]["duration_ms"] == 123

    # also support load by task_id (for chat: session_id == task_id)
    by_id_resp = client.get(f"/pipeline/load-latest?task_id={task_id}")
    assert by_id_resp.status_code == 200
    by_id = by_id_resp.json()
    assert by_id["task_id"] == task_id
    assert by_id["phases"]["detect"] == "done"

