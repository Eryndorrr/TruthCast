import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib import error, request

from app.core.logger import get_logger
from app.schemas.detect import StrategyConfig
from app.services.json_utils import safe_json_loads, serialize_for_json

logger = get_logger("truthcast.complexity")


@dataclass
class ScoreResult:
    label: str
    confidence: float
    score: int
    reasons: list[str]
    strategy: StrategyConfig | None = None


RISK_KEYWORDS = [
    "shocking",
    "internal source",
    "100% true",
    "share immediately",
    "before deleted",
    "cure all diseases",
]

TRUST_KEYWORDS = [
    "official statement",
    "source",
    "reporter",
    "published at",
    "data",
]


def analyze_text_complexity_with_llm(text: str) -> tuple[str, str, int] | None:
    api_key = os.getenv("TRUTHCAST_LLM_API_KEY", "").strip()
    if not api_key:
        logger.info("复杂度分析：TRUTHCAST_LLM_API_KEY为空，跳过LLM")
        return None
    
    if os.getenv("TRUTHCAST_COMPLEXITY_LLM_ENABLED", "false").strip().lower() != "true":
        logger.info("复杂度分析：LLM模式未启用")
        return None
    
    base_url = os.getenv("TRUTHCAST_LLM_BASE_URL", "https://api.openai.com/v1").strip()
    model = os.getenv("TRUTHCAST_COMPLEXITY_LLM_MODEL", os.getenv("TRUTHCAST_LLM_MODEL", "gpt-4o-mini")).strip()
    endpoint = base_url.rstrip("/") + "/chat/completions"
    max_claims_limit = 10
    
    prompt = (
        "你是文本复杂度分析器。分析输入文本的核查复杂度，输出严格JSON。\n"
        "判断标准：\n"
        "1. simple: 单一主题、单一实体、连贯叙述 → 2-3条主张\n"
        "2. medium: 2-3个关键实体、有时间线或多事件 → 4-5条主张\n"
        "3. complex: 多实体(>3)、多时间线、多转折、多独立事件 → 6-8条主张\n"
        "注意：纯数据(百分比、金额)不增加复杂度，只有额外的独立实体/事件/时间线才增加。\n"
        f"输出格式：{{\"level\":\"simple|medium|complex\",\"max_claims\":2-8,\"reason\":\"中文理由\"}}\n"
        f"max_claims 范围: 2-{min(8, max_claims_limit)}"
    )
    
    payload = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "你是严谨的文本分析助手，只返回JSON。"},
            {"role": "user", "content": f"{prompt}\n\n待分析文本：\n{text[:2000]}"},
        ],
    }
    
    _record_complexity_trace("llm_request", {"endpoint": endpoint, "payload": payload})
    
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
    
    timeout_val = float(os.getenv("TRUTHCAST_LLM_TIMEOUT", "30"))
    try:
        with request.urlopen(req, timeout=timeout_val) as resp:
            raw = resp.read().decode("utf-8")
    except (error.URLError, TimeoutError) as exc:
        logger.warning("复杂度分析：LLM请求失败，error=%s", exc)
        _record_complexity_trace("llm_error", {"error": str(exc)})
        return None
    
    try:
        body = json.loads(raw)
        content = body["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = content.replace("```json", "").replace("```", "").strip()
        
        parsed = safe_json_loads(content, "complexity_analysis")
        if parsed is None:
            logger.warning("复杂度分析：JSON解析失败")
            _record_complexity_trace("llm_parse_error", {"content": content})
            return None
        
        level = str(parsed.get("level", "medium")).strip().lower()
        if level not in {"simple", "medium", "complex"}:
            level = "medium"
        
        try:
            max_claims = int(parsed.get("max_claims", 5))
            max_claims = max(2, min(min(8, max_claims_limit), max_claims))
        except (TypeError, ValueError):
            max_claims = 5
        
        reason = str(parsed.get("reason", "LLM判定")).strip()
        
        logger.info("复杂度分析：LLM判定成功，level=%s, max_claims=%s", level, max_claims)
        _record_complexity_trace("llm_response", {"parsed": parsed, "level": level, "max_claims": max_claims})
        return level, reason, max_claims
        
    except Exception as exc:
        logger.warning("复杂度分析：LLM响应解析失败，error=%s", exc)
        _record_complexity_trace("llm_error", {"error": str(exc)})
        return None


def _record_complexity_trace(stage: str, payload: dict[str, Any]) -> None:
    if os.getenv("TRUTHCAST_DEBUG_COMPLEXITY", "false").strip().lower() != "true":
        return
    
    try:
        current_file = os.path.abspath(__file__)
        services_dir = os.path.dirname(current_file)
        app_dir = os.path.dirname(services_dir)
        project_root = os.path.dirname(app_dir)
        
        debug_dir = os.path.join(project_root, "debug")
        os.makedirs(debug_dir, exist_ok=True)
        trace_file = os.path.join(debug_dir, "complexity_trace.jsonl")
        
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            "payload": serialize_for_json(payload),
        }
        with open(trace_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.error("写入 complexity trace 失败: %s", exc)


def analyze_text_complexity_rule_based(text: str) -> tuple[str, str, int]:
    sentences = [s.strip() for s in re.split(r'[。！？!?\n]+', text) if len(s.strip()) > 5]
    sentence_count = len(sentences)
    
    avg_sentence_len = sum(len(s) for s in sentences) / max(1, sentence_count)
    
    entity_patterns = [
        r'[\u4e00-\u9fa5]{2,8}(?:公司|集团|银行|医院|政府|部门|机构|平台|人士|表示|称|宣布|通报)',
        r'[\u4e00-\u9fa5]{2,4}(?:说|指出|认为|透露|介绍)',
    ]
    all_entities = []
    for pattern in entity_patterns:
        all_entities.extend(re.findall(pattern, text))
    unique_entities = set(re.sub(r'(公司|集团|银行|医院|政府|部门|机构|平台|人士|表示|称|宣布|通报|说|指出|认为|透露|介绍)$', '', e) for e in all_entities)
    entity_count = len(unique_entities)
    
    date_refs = re.findall(r'\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日]?', text)
    relative_time = re.findall(r'昨天|今天|明天|上周|下周|本月|上月|前天|后天', text)
    time_refs = len(date_refs) + len(relative_time) * 0.5
    
    number_refs = len(re.findall(r'\d+(?:\.\d+)?[%％]|[\d,]+(?:万|亿|千|百)|\d+个(?:月|年|天)', text))
    
    transition_words = re.findall(r'然而|但是|另一方面|此外|与此同时|另外|首先|其次|最后', text)
    transition_count = len(transition_words)
    
    event_indicators = re.findall(r'发生|出现|导致|引起|造成|爆发|宣布|发布|启动|推出|调查|查处|逮捕|拘留', text)
    event_count = len(event_indicators)
    
    complexity_score = (
        min(sentence_count, 6) * 0.15 +
        max(0, entity_count - 1) * 0.6 +
        time_refs * 1.2 +
        transition_count * 0.8 +
        min(event_count, 4) * 0.6
    )
    
    if avg_sentence_len > 100:
        complexity_score += 0.5
    
    max_claims_limit = 10
    
    if complexity_score >= 5:
        level = "complex"
        max_claims = min(8, max_claims_limit)
        reason = f"复杂文本(实体{entity_count}个/时间线{int(time_refs)}个/转折{transition_count}个/事件{event_count}个)"
    elif complexity_score >= 2:
        level = "medium"
        max_claims = min(5, max_claims_limit)
        reason = f"中等文本(实体{entity_count}个/数据{number_refs}个)"
    else:
        level = "simple"
        max_claims = min(3, max_claims_limit)
        reason = f"简单文本(单主题叙事)"
    
    return level, reason, max_claims


def analyze_text_complexity(text: str) -> tuple[str, str, int]:
    llm_result = analyze_text_complexity_with_llm(text)
    if llm_result is not None:
        logger.info("复杂度分析：使用LLM结果")
        return llm_result
    
    logger.info("复杂度分析：LLM不可用，回退规则计算")
    return analyze_text_complexity_rule_based(text)


def infer_strategy(text: str, score: int, label: str) -> StrategyConfig:
    # score 为风险分（越高越危险），高风险时检索更多证据
    complexity_level, complexity_reason, max_claims = analyze_text_complexity(text)
    
    if score >= 65:
        evidence_per_claim = 10
        risk_level = "critical"
        risk_reason = f"高风险(score={score})，最大证据检索"
    elif score >= 45:
        evidence_per_claim = 7
        risk_level = "high"
        risk_reason = f"中高风险(score={score})，深度证据检索"
    elif score >= 25:
        evidence_per_claim = 5
        risk_level = "medium"
        risk_reason = f"中低风险(score={score})，标准证据检索"
    else:
        evidence_per_claim = 3
        risk_level = "low"
        risk_reason = f"低风险(score={score})，快速证据检索"
    
    summary_target_max = min(evidence_per_claim, 5)
    
    return StrategyConfig(
        max_claims=max_claims,
        complexity_level=complexity_level,
        complexity_reason=complexity_reason,
        evidence_per_claim=evidence_per_claim,
        risk_level=risk_level,
        risk_reason=risk_reason,
        summary_target_min=1,
        summary_target_max=summary_target_max,
        enable_summarization=True,
    )


def infer_strategy_from_score(score: int, label: str) -> StrategyConfig:
    return infer_strategy("", score, label)


def score_text(text: str) -> ScoreResult:
    # score 表示风险程度：越高风险越大（0=安全，100=极高风险）
    value = 50
    reasons: list[str] = []

    for word in RISK_KEYWORDS:
        if word in text:
            value += 12
            reasons.append(f"命中高风险词：{word}")

    for word in TRUST_KEYWORDS:
        if word in text:
            value -= 6
            reasons.append(f"命中可信线索词：{word}")

    if "http://" in text or "https://" in text:
        value -= 8
        reasons.append("包含可追溯链接")

    value = max(0, min(100, value))

    if value <= 30:
        label = "credible"
    elif value <= 60:
        label = "suspicious"
    else:
        label = "high_risk"

    confidence = round(abs(value - 50) / 50, 2)
    if not reasons:
        reasons.append("未发现明显风险或可信信号，建议人工复核")

    strategy = infer_strategy(text, value, label)
    return ScoreResult(label=label, confidence=confidence, score=value, reasons=reasons, strategy=strategy)
