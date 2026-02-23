import os
import tempfile
from pathlib import Path

# 确保 chat DB 不污染仓库目录（必须在导入 app 之前设置）
tmp_dir = Path(tempfile.gettempdir()) / "truthcast_test"
tmp_dir.mkdir(parents=True, exist_ok=True)
os.environ["TRUTHCAST_CHAT_DB_PATH"] = str(tmp_dir / "chat_test.db")
os.environ["TRUTHCAST_HISTORY_DB_PATH"] = str(tmp_dir / "history_test.db")

try:
    (tmp_dir / "history_test.db").unlink(missing_ok=True)  # type: ignore[arg-type]
except TypeError:
    # Python < 3.8 fallback (not expected here)
    if (tmp_dir / "history_test.db").exists():
        (tmp_dir / "history_test.db").unlink()

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def _extract_first_message_content_from_sse(raw: str) -> str:
    """从 SSE 文本中提取第一条 message 事件的 content。"""

    for line in raw.splitlines():
        if not line.startswith("data: "):
            continue
        try:
            evt = __import__("json").loads(line[len("data: ") :])
        except Exception:
            continue
        if evt.get("type") == "message":
            msg = (evt.get("data") or {}).get("message") or {}
            return str(msg.get("content") or "")
    return ""


def test_chat_smoke_returns_actions() -> None:
    resp = client.post("/chat", json={"text": "你好"})
    assert resp.status_code == 200
    body = resp.json()
    assert "session_id" in body
    assert "assistant_message" in body
    msg = body["assistant_message"]
    assert msg["role"] == "assistant"
    assert isinstance(msg.get("content"), str)
    assert isinstance(msg.get("actions"), list)
    assert len(msg["actions"]) >= 1


def test_chat_list_empty_shows_hint() -> None:
    # 确保在任何 /analyze 之前调用：历史库应为空
    with client.stream("POST", "/chat/stream", json={"text": "/list"}) as resp:
        assert resp.status_code == 200
        raw = "".join(list(resp.iter_text()))
        content = _extract_first_message_content_from_sse(raw)
        assert "暂无可用的历史记录" in content


def test_chat_why_without_record_id_shows_usage_not_error() -> None:
    with client.stream("POST", "/chat/stream", json={"text": "/why"}) as resp:
        assert resp.status_code == 200
        raw = "".join(list(resp.iter_text()))
        content = _extract_first_message_content_from_sse(raw)
        assert "用法：/why" in content


def test_chat_why_can_fallback_to_context_record_id() -> None:
    # 1) 先生成一条 history record
    resp = client.post("/chat", json={"text": "/analyze 网传某事件100%真实，内部人士称必须立刻转发。"})
    assert resp.status_code == 200
    actions = (resp.json().get("assistant_message") or {}).get("actions") or []
    load_cmd = None
    for a in actions:
        if a.get("type") == "command" and str(a.get("command", "")).startswith("/load_history "):
            load_cmd = a.get("command")
            break
    assert load_cmd
    record_id = str(load_cmd).split()[-1]

    # 2) /chat/stream：只输入 /why，但在 context 带 record_id，应返回解释而不是用法提示
    with client.stream(
        "POST",
        "/chat/stream",
        json={"text": "/why", "context": {"record_id": record_id}},
    ) as resp2:
        assert resp2.status_code == 200
        raw2 = "".join(list(resp2.iter_text()))
        content2 = _extract_first_message_content_from_sse(raw2)
        assert "解释（最小可用）" in content2


def test_chat_analyze_command_works() -> None:
    resp = client.post("/chat", json={"text": "/analyze 网传某事件100%真实，内部人士称必须立刻转发。"})
    assert resp.status_code == 200
    body = resp.json()
    msg = body["assistant_message"]
    assert "已完成一次全链路分析" in msg["content"]
    assert isinstance(msg.get("references"), list)
    actions = msg.get("actions") or []
    assert any((a.get("type") == "command" and str(a.get("command", "")).startswith("/load_history ")) for a in actions)

    load_cmd = None
    for a in actions:
        if a.get("type") == "command" and str(a.get("command", "")).startswith("/load_history "):
            load_cmd = a.get("command")
            break
    assert load_cmd

    # /why <record_id> 应可解释原因（追问闭环最小可用）
    why_cmd = None
    for a in actions:
        if a.get("type") == "command" and str(a.get("command", "")).startswith("/why "):
            why_cmd = a.get("command")
            break
    assert why_cmd

    resp2 = client.post("/chat", json={"text": why_cmd})
    assert resp2.status_code == 200
    msg2 = resp2.json()["assistant_message"]
    assert "解释（最小可用）" in msg2["content"]
    meta = msg2.get("meta") or {}
    blocks = meta.get("blocks") or []
    assert isinstance(blocks, list)
    assert any((b or {}).get("kind") == "section" for b in blocks)

    # /rewrite 与 /more_evidence（通过 context 兜底 record_id）
    record_id = str(load_cmd).split()[-1]
    with client.stream(
        "POST",
        "/chat/stream",
        json={"text": "/rewrite short", "context": {"record_id": record_id}},
    ) as resp3:
        assert resp3.status_code == 200
        raw3 = "".join(list(resp3.iter_text()))
        content3 = _extract_first_message_content_from_sse(raw3)
        assert "改写" in content3

    with client.stream(
        "POST",
        "/chat/stream",
        json={"text": "/more_evidence", "context": {"record_id": record_id}},
    ) as resp4:
        assert resp4.status_code == 200
        raw4 = "".join(list(resp4.iter_text()))
        content4 = _extract_first_message_content_from_sse(raw4)
        assert "补充证据建议" in content4


def test_chat_stream_smoke_for_non_analyze_intent() -> None:
    # 避免触发真实全链路分析：短输入应直接返回 message + done
    with client.stream("POST", "/chat/stream", json={"text": "你好"}) as resp:
        assert resp.status_code == 200
        raw = "".join(list(resp.iter_text()))
        assert "data: " in raw
        # 至少应包含 done 事件
        assert '"type":"done"' in raw or '"type": "done"' in raw


def test_chat_sessions_crud_smoke() -> None:
    resp = client.post("/chat/sessions", json={})
    assert resp.status_code == 200
    session = resp.json()
    assert session.get("session_id")

    resp2 = client.get("/chat/sessions")
    assert resp2.status_code == 200
    body = resp2.json()
    assert isinstance(body.get("sessions"), list)
    assert any(s.get("session_id") == session["session_id"] for s in body["sessions"])

    resp3 = client.get(f"/chat/sessions/{session['session_id']}")
    assert resp3.status_code == 200
    detail = resp3.json()
    assert detail.get("session", {}).get("session_id") == session["session_id"]
    assert isinstance(detail.get("messages"), list)


def test_chat_session_stream_smoke() -> None:
    resp = client.post("/chat/sessions", json={})
    assert resp.status_code == 200
    session_id = resp.json()["session_id"]

    with client.stream(
        "POST",
        f"/chat/sessions/{session_id}/messages/stream",
        json={"text": "你好", "context": None},
    ) as resp2:
        assert resp2.status_code == 200
        raw = "".join(list(resp2.iter_text()))
        assert "data: " in raw
        assert '"type":"done"' in raw or '"type": "done"' in raw


def test_chat_list_then_analyze_then_load_history() -> None:
    # 1) 先 analyze 生成一条 history
    resp2 = client.post("/chat", json={"text": "/analyze 网传某事件100%真实，内部人士称必须立刻转发。"})
    assert resp2.status_code == 200
    actions = (resp2.json().get("assistant_message") or {}).get("actions") or []
    load_cmd = None
    for a in actions:
        if a.get("type") == "command" and str(a.get("command", "")).startswith("/load_history "):
            load_cmd = a.get("command")
            break
    assert load_cmd
    record_id = str(load_cmd).split()[-1]

    # 2) /sessions/{id}/messages/stream：/list 1 能列出 record_id
    resp3 = client.post("/chat/sessions", json={})
    assert resp3.status_code == 200
    session_id = resp3.json()["session_id"]

    with client.stream(
        "POST",
        f"/chat/sessions/{session_id}/messages/stream",
        json={"text": "/list 1", "context": None},
    ) as resp4:
        assert resp4.status_code == 200
        raw = "".join(list(resp4.iter_text()))
        content = _extract_first_message_content_from_sse(raw)
        assert record_id in content
        assert "/load_history" in content

    # 3) /load_history 串联可用
    with client.stream(
        "POST",
        f"/chat/sessions/{session_id}/messages/stream",
        json={"text": f"/load_history {record_id}", "context": None},
    ) as resp5:
        assert resp5.status_code == 200
        raw = "".join(list(resp5.iter_text()))
        content = _extract_first_message_content_from_sse(raw)
        assert "已定位到历史记录" in content

