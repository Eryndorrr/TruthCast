import json
import os
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any
from urllib import error, request

from app.core.logger import get_logger
from app.services.text_complexity import ScoreResult, infer_strategy, score_text
from app.services.json_utils import serialize_for_json

logger = get_logger("truthcast.risk_snapshot")

VALID_LABELS = {
    "credible",
    "suspicious",
    "high_risk",
    "needs_context",
    "likely_misinformation",
}

_LABEL_ZH_TO_EN = {
    "可信": "credible",
    "可疑": "suspicious",
    "高风险": "high_risk",
    "需要补充语境": "needs_context",
    "疑似不实信息": "likely_misinformation",
    "疑似不实": "likely_misinformation",
    "不实信息": "likely_misinformation",
}


def _normalize_label(label_raw: str) -> str:
    """将中文/英文 label 统一转换为英文标准值"""
    label = str(label_raw).strip().lower()
    if label in VALID_LABELS:
        return label
    label_zh = str(label_raw).strip()
    if label_zh in _LABEL_ZH_TO_EN:
        return _LABEL_ZH_TO_EN[label_zh]
    return "needs_context"


def detect_risk_snapshot(text: str) -> ScoreResult:
    _record_risk_trace("input", {"text": text})

    if _risk_llm_enabled():
        logger.info("风险快照：LLM模式已启用，开始尝试LLM判定")
        llm_result = _detect_with_llm(text)
        if llm_result is not None:
            logger.info(
                "风险快照：LLM判定成功，label=%s, score=%s",
                llm_result.label,
                llm_result.score,
            )
            _record_risk_trace(
                "output",
                {
                    "path": "llm",
                    "result": asdict(llm_result),
                },
            )
            return llm_result
        logger.warning("风险快照：LLM判定失败，已回退规则评分")
    else:
        logger.info("风险快照：LLM模式未启用，使用规则评分")

    rule_result = score_text(text)
    _record_risk_trace(
        "output",
        {
            "path": "rule",
            "result": asdict(rule_result),
        },
    )
    return rule_result


def _risk_llm_enabled() -> bool:
    direct = os.getenv("TRUTHCAST_RISK_LLM_ENABLED", "").strip().lower()
    if direct in {"true", "false"}:
        return direct == "true"
    return os.getenv("TRUTHCAST_LLM_ENABLED", "false").strip().lower() == "true"


def _detect_with_llm(text: str) -> ScoreResult | None:
    api_key = os.getenv("TRUTHCAST_LLM_API_KEY", "").strip()
    if not api_key:
        logger.warning("风险快照：TRUTHCAST_LLM_API_KEY为空，无法调用LLM")
        return None

    base_url = os.getenv("TRUTHCAST_LLM_BASE_URL", "https://api.openai.com/v1").strip()
    model = os.getenv(
        "TRUTHCAST_RISK_LLM_MODEL",
        os.getenv("TRUTHCAST_LLM_MODEL", "gpt-4o-mini"),
    ).strip()
    endpoint = base_url.rstrip("/") + "/chat/completions"
    prompt = (
        "你是风险快照判定器。请根据输入文本输出严格JSON："
        '{"label":"可信|可疑|高风险|需要补充语境|疑似不实信息",'
        '"score":0-100,"confidence":0-1,"reasons":["中文理由1","中文理由2"]}。'
        "其中 score 表示风险程度，越高表示风险越大（0=完全可信，100=极高风险）。"
        "label 与 score 对应关系：可信(0-30)、需要补充语境/可疑(31-60)、高风险/疑似不实信息(61-100)。"
        "不要输出任何额外说明。"
    )

    payload = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "你是严谨的风险评估助手，只返回JSON。"},
            {"role": "user", "content": f"{prompt}\n\n待分析文本：\n{text}"},
        ],
    }

    timeout_val = float(os.getenv("TRUTHCAST_LLM_TIMEOUT", "60"))
    _record_risk_trace(
        "llm_request",
        {
            "endpoint": endpoint,
            "timeout": timeout_val,
            "llm_payload": payload,
        },
    )

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        endpoint,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=timeout_val) as resp:
            raw = resp.read().decode("utf-8")
    except (error.URLError, TimeoutError) as exc:
        logger.error("风险快照：LLM请求失败，错误=%s", exc)
        _record_risk_trace("llm_error", {"error": str(exc)})
        return None

    try:
        body = json.loads(raw)
        content_raw = body["choices"][0]["message"]["content"]
        content = content_raw.strip()
        if content.startswith("```"):
            content = content.replace("```json", "").replace("```", "").strip()
        
        from app.services.json_utils import safe_json_loads
        
        parsed = safe_json_loads(content, "risk_snapshot")
        if parsed is None:
            logger.error("风险快照：JSON解析失败")
            _record_risk_trace("llm_parse_error", {"error": "JSON parse failed", "content_cleaned": content})
            return None
        
        _record_risk_trace(
            "llm_response",
            {
                "llm_raw_http_response": body,
                "llm_content_raw": content_raw,
                "llm_content_cleaned": content,
                "parsed_json": parsed,
            },
        )
        return _normalize_llm_result(parsed, text)
    except Exception as exc:  # noqa: BLE001
        logger.error("风险快照：LLM响应解析失败，错误=%s", exc)
        _record_risk_trace("llm_error", {"error": str(exc)})
        return None


def _normalize_llm_result(payload: dict[str, Any], text: str) -> ScoreResult | None:
    label_raw = payload.get("label", "")
    label = _normalize_label(label_raw)
    if label not in VALID_LABELS:
        return None

    try:
        score = int(float(payload.get("score", 50)))
    except (TypeError, ValueError):
        score = 50
    score = max(0, min(100, score))

    try:
        confidence = float(payload.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))

    reasons_raw = payload.get("reasons", [])
    if not isinstance(reasons_raw, list):
        reasons_raw = []
    reasons = [str(item).strip() for item in reasons_raw if str(item).strip()]
    if not reasons:
        reasons = ["模型未返回理由，建议人工复核。"]

    strategy = infer_strategy(text, score, label)
    return ScoreResult(
        label=label,
        score=score,
        confidence=round(confidence, 2),
        reasons=reasons[:5],
        strategy=strategy,
    )


def _record_risk_trace(stage: str, payload: dict[str, Any]) -> None:
    if os.getenv("TRUTHCAST_DEBUG_RISK_SNAPSHOT", "true").strip().lower() != "true":
        return

    try:
        current_file = os.path.abspath(__file__)
        services_dir = os.path.dirname(current_file)
        app_dir = os.path.dirname(services_dir)
        project_root = os.path.dirname(app_dir)

        debug_dir = os.path.join(project_root, "debug")
        os.makedirs(debug_dir, exist_ok=True)
        trace_file = os.path.join(debug_dir, "risk_snapshot_trace.jsonl")

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            "payload": serialize_for_json(payload),
        }
        with open(trace_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001
        logger.error("写入 risk snapshot trace 失败: %s", exc)
