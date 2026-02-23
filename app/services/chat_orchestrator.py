from __future__ import annotations

import re
from typing import Any, Iterator, Literal

from pydantic import BaseModel, Field

from app.core.concurrency import llm_slot
from app.orchestrator import orchestrator
from app.schemas.chat import ChatAction, ChatMessage, ChatReference, ChatStreamEvent
from app.services.history_store import get_history, list_history, save_report
from app.services.pipeline import align_evidences
from app.services.risk_snapshot import detect_risk_snapshot


class ToolAnalyzeArgs(BaseModel):
    text: str = Field(min_length=1, max_length=12000)


class ToolLoadHistoryArgs(BaseModel):
    record_id: str = Field(min_length=1, max_length=128)


class ToolWhyArgs(BaseModel):
    record_id: str = Field(min_length=1, max_length=128)


class ToolListArgs(BaseModel):
    limit: int = Field(default=10, ge=0, le=50)


class ToolMoreEvidenceArgs(BaseModel):
    record_id: str = Field(min_length=1, max_length=128)


class ToolRewriteArgs(BaseModel):
    record_id: str = Field(min_length=1, max_length=128)
    style: str = Field(default="short", max_length=32)


ToolName = Literal["analyze", "load_history", "why", "list", "more_evidence", "rewrite", "help"]


def _is_analyze_intent(text: str) -> bool:
    t = text.strip()
    if t.startswith("/analyze"):
        return True
    # 粗略启发：超长输入大概率是待分析文本
    return len(t) >= 180


def _extract_analyze_text(text: str) -> str:
    t = text.strip()
    if t.startswith("/analyze"):
        return t[len("/analyze") :].strip()
    return t


def parse_tool(text: str) -> tuple[ToolName, dict[str, Any]]:
    """把用户输入解析为后端允许的工具调用。

    约束：只允许白名单工具。
    """

    t = text.strip()
    if not t:
        return ("help", {})

    if t.startswith("/load_history"):
        parts = re.split(r"\s+", t)
        record_id = parts[1] if len(parts) >= 2 else ""
        return ("load_history", {"record_id": record_id})

    if t.startswith("/why") or t.startswith("/explain"):
        parts = re.split(r"\s+", t)
        record_id = parts[1] if len(parts) >= 2 else ""
        return ("why", {"record_id": record_id})

    if t.startswith("/list") or t.startswith("/history") or t.startswith("/records"):
        # 支持：/list 20 或 /list limit=20
        parts = re.split(r"\s+", t)
        limit = 10
        if len(parts) >= 2:
            raw = parts[1].strip()
            if raw.startswith("limit="):
                raw = raw[len("limit=") :]
            try:
                limit = int(raw)
            except ValueError:
                limit = 10
        return ("list", {"limit": limit})

    if t.startswith("/more_evidence") or t.startswith("/more"):
        # 支持：/more_evidence（record_id 将在路由层从 context 兜底）
        return ("more_evidence", {"record_id": ""})

    if t.startswith("/rewrite"):
        # 支持：/rewrite [style]（record_id 将在路由层从 context 兜底）
        # style: short/neutral/friendly
        parts = re.split(r"\s+", t)
        style = parts[1].strip() if len(parts) >= 2 else "short"
        if style.startswith("style="):
            style = style[len("style=") :]
        return ("rewrite", {"record_id": "", "style": style})

    if _is_analyze_intent(t):
        analyze_text = _extract_analyze_text(t)
        return ("analyze", {"text": analyze_text})

    return ("help", {})


def build_help_message() -> ChatMessage:
    return ChatMessage(
        role="assistant",
        content=(
            "当前对话工作台已启用后端工具白名单编排（V2）。\n\n"
            "可用命令：\n"
            "- /analyze <待分析文本>：发起全链路分析\n"
            "- /load_history <record_id>：加载历史记录到前端上下文\n\n"
            "- /why <record_id>：解释为什么给出该风险/结论（最小可用）\n\n"
            "- /list [N]：列出最近 N 条历史记录的 record_id（默认 10，例如 /list 20）\n\n"
            "- /more_evidence：基于当前上下文，给出补充证据的下一步动作（例如重试证据阶段）\n"
            "- /rewrite [short|neutral|friendly]：基于当前上下文，将解释改写为更短/更中性/更亲切的版本\n\n"
            "record_id 来源：分析完成后会写入历史记录；也可以用 /list 查询后再 /load_history {record_id}。\n\n"
            "你也可以直接粘贴长文本（系统会自动视为待分析内容）。"
        ),
        actions=[
            ChatAction(type="link", label="检测结果", href="/result"),
            ChatAction(type="link", label="历史记录", href="/history"),
        ],
        references=[],
    )


def build_why_usage_message() -> ChatMessage:
    return ChatMessage(
        role="assistant",
        content=(
            "用法：/why <record_id>\n\n"
            "- 先使用 /list 查看最近的 record_id\n"
            "- 或先 /load_history <record_id> 加载到前端上下文后再追问\n"
        ),
        actions=[
            ChatAction(type="command", label="列出最近记录（/list）", command="/list"),
            ChatAction(type="link", label="打开历史记录页面", href="/history"),
        ],
        references=[],
    )


def run_more_evidence(args: ToolMoreEvidenceArgs) -> ChatMessage:
    record = get_history(args.record_id)
    if not record:
        return ChatMessage(
            role="assistant",
            content=f"未找到历史记录：{args.record_id}。",
            actions=[ChatAction(type="link", label="打开历史记录", href="/history")],
            references=[],
        )

    return ChatMessage(
        role="assistant",
        content=(
            "补充证据建议（V1）：\n"
            "- 点击下方按钮重试【证据检索】阶段，以获取更多候选证据\n"
            "- 若证据已更新，可再重试【综合报告】阶段刷新结论\n"
        ),
        actions=[
            ChatAction(type="command", label="重试证据检索（/retry evidence）", command="/retry evidence"),
            ChatAction(type="command", label="重试综合报告（/retry report）", command="/retry report"),
            ChatAction(type="link", label="打开检测结果", href="/result"),
        ],
        references=[
            ChatReference(
                title=f"历史记录：{record['id']}",
                href="/history",
                description=f"风险: {record.get('risk_label')}（{record.get('risk_score')}） · 时间: {record.get('created_at')}",
            )
        ],
        meta={"record_id": record["id"]},
    )


def run_rewrite(args: ToolRewriteArgs) -> ChatMessage:
    record = get_history(args.record_id)
    if not record:
        return ChatMessage(
            role="assistant",
            content=f"未找到历史记录：{args.record_id}。",
            actions=[ChatAction(type="link", label="打开历史记录", href="/history")],
            references=[],
        )

    style = (args.style or "short").strip().lower()
    if style not in {"short", "neutral", "friendly"}:
        style = "short"

    detect_data = record.get("detect_data") or {}
    report = record.get("report") or {}
    reasons = detect_data.get("reasons") or []
    suspicious_points = report.get("suspicious_points") or []

    risk_label = report.get("risk_label", record.get("risk_label"))
    risk_score = report.get("risk_score", record.get("risk_score"))

    if style == "short":
        content = (
            f"改写（短版）：结论为【{risk_label}】（score={risk_score}）。\n"
            + ("风险快照原因：" + "；".join([str(x) for x in reasons[:3]]) + "\n" if reasons else "")
            + ("可疑点：" + "；".join([str(x) for x in suspicious_points[:3]]) + "\n" if suspicious_points else "")
            + "（提示：可用 /more_evidence 或 /retry evidence 补充证据）"
        )
    elif style == "friendly":
        content = (
            f"改写（亲切版）：目前的辅助判断是【{risk_label}】（score={risk_score}）。\n"
            "我主要参考了风险快照的触发原因，以及报告里整理的可疑点/证据对齐结果。\n"
            + ("你可以重点留意：\n- " + "\n- ".join([str(x) for x in suspicious_points[:3]]) + "\n" if suspicious_points else "")
            + "如果你希望我再多找一些证据，可以直接输入 /more_evidence。"
        )
    else:
        content = (
            f"改写（中性版）：综合判断为【{risk_label}】（score={risk_score}）。\n"
            "依据来源：风险快照触发原因 + 报告可疑点 + 主张-证据对齐结果。\n"
            + ("风险快照原因（节选）：\n- " + "\n- ".join([str(x) for x in reasons[:3]]) + "\n" if reasons else "")
            + ("报告可疑点（节选）：\n- " + "\n- ".join([str(x) for x in suspicious_points[:3]]) + "\n" if suspicious_points else "")
        )

    return ChatMessage(
        role="assistant",
        content=content,
        actions=[
            ChatAction(type="command", label="补充证据（/more_evidence）", command="/more_evidence"),
            ChatAction(type="link", label="打开检测结果", href="/result"),
        ],
        references=[
            ChatReference(
                title=f"历史记录：{record['id']}",
                href="/history",
                description=f"风险: {record.get('risk_label')}（{record.get('risk_score')}） · 时间: {record.get('created_at')}",
            )
        ],
        meta={"record_id": record["id"], "style": style},
    )


def run_load_history(args: ToolLoadHistoryArgs) -> ChatMessage:
    record = get_history(args.record_id)
    if not record:
        return ChatMessage(
            role="assistant",
            content=f"未找到历史记录：{args.record_id}。",
            actions=[ChatAction(type="link", label="打开历史记录", href="/history")],
            references=[],
        )

    refs: list[ChatReference] = [
        ChatReference(
            title=f"历史记录：{record['id']}",
            href="/history",
            description=f"风险: {record.get('risk_label')}（{record.get('risk_score')}） · 时间: {record.get('created_at')}",
        )
    ]

    return ChatMessage(
        role="assistant",
        content=(
            "已定位到历史记录。你可以点击下方命令，将其加载到前端上下文（pipeline-store），然后到结果页查看模块化结果。"
        ),
        actions=[
            ChatAction(type="command", label="加载到前端上下文", command=f"/load_history {record['id']}"),
            ChatAction(type="link", label="打开检测结果", href="/result"),
        ],
        references=refs,
        meta={"record_id": record["id"]},
    )


def run_why(args: ToolWhyArgs) -> ChatMessage:
    record = get_history(args.record_id)
    if not record:
        return ChatMessage(
            role="assistant",
            content=f"未找到历史记录：{args.record_id}。",
            actions=[ChatAction(type="link", label="打开历史记录", href="/history")],
            references=[],
        )

    detect_data = record.get("detect_data") or {}
    report = record.get("report") or {}

    reasons = detect_data.get("reasons") or []
    suspicious_points = report.get("suspicious_points") or []
    claim_reports = report.get("claim_reports") or []

    refs: list[ChatReference] = [
        ChatReference(
            title=f"历史记录：{record['id']}",
            href="/history",
            description=f"风险: {record.get('risk_label')}（{record.get('risk_score')}） · 时间: {record.get('created_at')}",
        )
    ]

    seen_urls: set[str] = set()
    for row in claim_reports[:3]:
        for ev in (row.get("evidences") or [])[:3]:
            url = str(ev.get("url") or "").strip()
            title = str(ev.get("title") or url).strip()
            if not url or not url.startswith("http"):
                continue
            if url in seen_urls:
                continue
            seen_urls.add(url)
            refs.append(
                ChatReference(
                    title=title[:80] or url,
                    href=url,
                    description=f"证据立场: {ev.get('stance')} · 置信度: {ev.get('alignment_confidence')}",
                )
            )
            if len(refs) >= 8:
                break
        if len(refs) >= 8:
            break

    # ====== 结构化 blocks（供前端做“引用卡片/折叠区块”展示）======
    # 约定：写入 ChatMessage.meta.blocks，不改动顶层 schema，便于渐进增强与持久化。
    blocks: list[dict[str, Any]] = []

    if reasons:
        blocks.append(
            {
                "kind": "section",
                "title": "风险快照触发原因",
                "items": [str(r) for r in reasons[:5]],
                "collapsed": False,
            }
        )
    if suspicious_points:
        blocks.append(
            {
                "kind": "section",
                "title": "报告可疑点",
                "items": [str(p) for p in suspicious_points[:5]],
                "collapsed": True,
            }
        )
    if claim_reports:
        items: list[str] = []
        for row in claim_reports[:3]:
            claim_text = (row.get("claim") or {}).get("claim_text") or ""
            verdict = row.get("verdict") or ""
            items.append(f"主张：{claim_text[:60]}… → 结论：{verdict}")
        if items:
            blocks.append(
                {
                    "kind": "section",
                    "title": "主张级证据对齐（节选）",
                    "items": items,
                    "collapsed": True,
                }
            )

    # refs[0] 是历史记录入口；其余多为证据链接
    if len(refs) > 1:
        blocks.append(
            {
                "kind": "links",
                "title": f"证据链接（节选 {len(refs) - 1} 条）",
                "links": [r.model_dump() for r in refs[1:]],
                "collapsed": True,
            }
        )

    lines: list[str] = []
    lines.append("解释（最小可用）：本结论来自风险快照 + 报告阶段对主张与证据的综合判断。")
    lines.append("")
    lines.append(
        f"- 风险快照：{detect_data.get('label', record.get('risk_label'))}（score={detect_data.get('score', record.get('risk_score'))}）"
    )
    if reasons:
        lines.append("  - 触发原因：")
        for r in reasons[:5]:
            lines.append(f"    - {r}")

    lines.append(
        f"- 综合报告：{report.get('risk_label', record.get('risk_label'))}（score={report.get('risk_score', record.get('risk_score'))}）"
    )
    if suspicious_points:
        lines.append("  - 可疑点摘要：")
        for p in suspicious_points[:5]:
            lines.append(f"    - {p}")

    if claim_reports:
        lines.append("  - 主张级证据对齐（节选）：")
        for row in claim_reports[:3]:
            claim_text = (row.get("claim") or {}).get("claim_text") or ""
            verdict = row.get("verdict") or ""
            lines.append(f"    - 主张：{claim_text[:60]}… → 结论：{verdict}")

    lines.append("")
    lines.append("提示：你可以先加载该 record_id 到前端上下文，再打开结果页查看完整模块化结果与证据链。")

    return ChatMessage(
        role="assistant",
        content="\n".join(lines),
        actions=[
            ChatAction(type="command", label="加载到前端上下文", command=f"/load_history {record['id']}"),
            ChatAction(type="command", label="补充证据（/more_evidence）", command="/more_evidence"),
            ChatAction(type="command", label="改写为短版（/rewrite short）", command="/rewrite short"),
            ChatAction(type="command", label="改写为中性版（/rewrite neutral）", command="/rewrite neutral"),
            ChatAction(type="command", label="改写为亲切版（/rewrite friendly）", command="/rewrite friendly"),
            ChatAction(type="command", label="重试证据检索（/retry evidence）", command="/retry evidence"),
            ChatAction(type="command", label="重试综合报告（/retry report）", command="/retry report"),
            ChatAction(type="link", label="打开检测结果", href="/result"),
            ChatAction(type="link", label="打开历史记录", href="/history"),
        ],
        references=refs,
        meta={"record_id": record["id"], "blocks": blocks},
    )


def run_list(args: ToolListArgs) -> ChatMessage:
    limit = int(args.limit)
    rows = list_history(limit=limit)

    if not rows:
        return ChatMessage(
            role="assistant",
            content=(
                "暂无可用的历史记录。\n\n"
                "你可以先发送 `/analyze <待分析文本>` 生成一次分析；或稍后再试。"
            ),
            actions=[
                ChatAction(type="command", label="示例：开始分析", command="/analyze 网传某事件100%真实，内部人士称..."),
                ChatAction(type="link", label="打开历史记录", href="/history"),
            ],
            references=[],
        )

    lines: list[str] = []
    lines.append(f"最近 {len(rows)} 条历史记录（可用于 /load_history）：")
    for idx, r in enumerate(rows, start=1):
        rid = r.get("id")
        created_at = r.get("created_at")
        preview = r.get("input_preview") or ""
        risk_label = r.get("risk_label")
        risk_score = r.get("risk_score")
        lines.append(f"{idx}. {rid} · {created_at} · {risk_label}({risk_score})")
        if preview:
            lines.append(f"   摘要: {preview}")
    lines.append("")
    lines.append("用法：/load_history <record_id>（例如：/load_history " + str(rows[0].get("id")) + ")")

    actions: list[ChatAction] = [
        ChatAction(type="link", label="打开历史记录", href="/history"),
    ]
    first_id = rows[0].get("id")
    if first_id:
        actions.insert(0, ChatAction(type="command", label="加载最新记录到前端", command=f"/load_history {first_id}"))

    return ChatMessage(
        role="assistant",
        content="\n".join(lines),
        actions=actions,
        references=[],
    )


def run_analyze_stream(session_id: str, args: ToolAnalyzeArgs) -> Iterator[str]:
    """执行 analyze 工具并通过 SSE 输出 token + 最终 message 事件。"""

    text = args.text.strip()
    if not text:
        msg = ChatMessage(
            role="assistant",
            content="用法：/analyze <待分析文本>。",
            actions=[ChatAction(type="link", label="检测结果", href="/result")],
            references=[],
        )
        event = ChatStreamEvent(type="message", data={"session_id": session_id, "message": msg.model_dump()})
        yield f"data: {event.model_dump_json()}\n\n"
        return

    yield f"data: {ChatStreamEvent(type='token', data={'content': '已收到文本，开始分析…\n', 'session_id': session_id}).model_dump_json()}\n\n"

    # 风险快照
    yield f"data: {ChatStreamEvent(type='token', data={'content': '- 风险快照：计算中…\n', 'session_id': session_id}).model_dump_json()}\n\n"
    with llm_slot():
        risk = detect_risk_snapshot(text)
    yield f"data: {ChatStreamEvent(type='token', data={'content': f'- 风险快照：完成（{risk.label}，score={risk.score}）\n', 'session_id': session_id}).model_dump_json()}\n\n"

    # 主张
    yield f"data: {ChatStreamEvent(type='token', data={'content': '- 主张抽取：进行中…\n', 'session_id': session_id}).model_dump_json()}\n\n"
    with llm_slot():
        claims = orchestrator.run_claims(text, strategy=risk.strategy)
    yield f"data: {ChatStreamEvent(type='token', data={'content': f'- 主张抽取：完成（{len(claims)} 条）\n', 'session_id': session_id}).model_dump_json()}\n\n"

    # 证据检索
    yield f"data: {ChatStreamEvent(type='token', data={'content': '- 联网检索证据：进行中…\n', 'session_id': session_id}).model_dump_json()}\n\n"
    evidences = orchestrator.run_evidence(text=text, claims=claims, strategy=risk.strategy)
    yield f"data: {ChatStreamEvent(type='token', data={'content': f'- 联网检索证据：完成（候选 {len(evidences)} 条）\n', 'session_id': session_id}).model_dump_json()}\n\n"

    # 证据聚合与对齐
    yield f"data: {ChatStreamEvent(type='token', data={'content': '- 证据聚合与对齐：进行中…\n', 'session_id': session_id}).model_dump_json()}\n\n"
    with llm_slot():
        aligned = align_evidences(claims=claims, evidences=evidences, strategy=risk.strategy)
    yield f"data: {ChatStreamEvent(type='token', data={'content': f'- 证据聚合与对齐：完成（对齐 {len(aligned)} 条）\n', 'session_id': session_id}).model_dump_json()}\n\n"

    # 报告
    yield f"data: {ChatStreamEvent(type='token', data={'content': '- 综合报告：生成中…\n', 'session_id': session_id}).model_dump_json()}\n\n"
    with llm_slot():
        report = orchestrator.run_report(text=text, claims=claims, evidences=aligned, strategy=risk.strategy)
    yield f"data: {ChatStreamEvent(type='token', data={'content': '- 综合报告：完成\n', 'session_id': session_id}).model_dump_json()}\n\n"

    record_id = save_report(
        input_text=text,
        report=report,
        detect_data={
            "label": risk.label,
            "confidence": risk.confidence,
            "score": risk.score,
            "reasons": risk.reasons,
        },
    )

    top_refs: list[ChatReference] = [
        ChatReference(
            title=f"历史记录已保存：{record_id}",
            href="/history",
            description="可在历史记录页查看详情并回放。",
        )
    ]
    for item in aligned[:5]:
        if item.url and item.url.startswith("http"):
            top_refs.append(
                ChatReference(
                    title=item.title[:80] or item.url,
                    href=item.url,
                    description=f"立场: {item.stance} · 置信度: {item.alignment_confidence}",
                )
            )

    msg = ChatMessage(
        role="assistant",
        content=(
            "已完成一次全链路分析，并写入历史记录。\n\n"
            f"- 风险快照: {risk.label}（score={risk.score}）\n"
            f"- 主张数: {len(claims)}\n"
            f"- 对齐证据数: {len(aligned)}\n"
            f"- 报告风险: {report.get('risk_label')}（{report.get('risk_score')}）\n"
            f"- 场景: {report.get('detected_scenario')}\n"
        ),
        actions=[
            ChatAction(type="link", label="打开检测结果", href="/result"),
            ChatAction(type="link", label="打开历史记录", href="/history"),
            ChatAction(type="command", label="加载本次结果到前端", command=f"/load_history {record_id}"),
            ChatAction(type="command", label="为什么这样判定", command=f"/why {record_id}"),
        ],
        references=top_refs,
        meta={"record_id": record_id},
    )

    event = ChatStreamEvent(type="message", data={"session_id": session_id, "message": msg.model_dump()})
    yield f"data: {event.model_dump_json()}\n\n"

