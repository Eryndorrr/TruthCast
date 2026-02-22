"""
多平台话术生成模块

根据澄清稿和检测结果，生成适配不同平台的发布话术。
支持 9 个平台：
- 微博、微信公众号、短视频口播(通用)
- 新闻通稿、官方声明
- 小红书、抖音、快手、B站
"""

import json
import os
from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.logger import get_logger
from app.schemas.detect import (
    ClarificationContent,
    PlatformScript,
    Platform,
    ReportResponse,
    SimulateResponse,
)
from app.services.json_utils import safe_json_loads, serialize_for_json

logger = get_logger(__name__)

# 配置
CONTENT_LLM_ENABLED = os.getenv("TRUTHCAST_CONTENT_LLM_ENABLED", "false").lower() == "true"
CONTENT_LLM_MODEL = os.getenv("TRUTHCAST_CONTENT_LLM_MODEL", "")
CONTENT_LLM_BASE_URL = os.getenv("TRUTHCAST_CONTENT_LLM_BASE_URL", os.getenv("TRUTHCAST_LLM_BASE_URL", "https://api.openai.com/v1"))
CONTENT_LLM_API_KEY = os.getenv("TRUTHCAST_CONTENT_LLM_API_KEY", os.getenv("TRUTHCAST_LLM_API_KEY", ""))
CONTENT_TIMEOUT_SEC = int(os.getenv("TRUTHCAST_CONTENT_TIMEOUT_SEC", "45"))
DEBUG_CONTENT = os.getenv("TRUTHCAST_DEBUG_CONTENT", "true").lower() == "true"

# 平台字数限制
PLATFORM_WEIBO_MAX = int(os.getenv("TRUTHCAST_PLATFORM_WEIBO_MAX", "280"))
PLATFORM_WECHAT_MAX = int(os.getenv("TRUTHCAST_PLATFORM_WECHAT_MAX", "1000"))
PLATFORM_XIAOHONGSHU_MAX = int(os.getenv("TRUTHCAST_PLATFORM_XIAOHONGSHU_MAX", "500"))
PLATFORM_DOUYIN_MAX_SEC = int(os.getenv("TRUTHCAST_PLATFORM_DOUYIN_MAX_SEC", "60"))
PLATFORM_KUAISHOU_MAX_SEC = int(os.getenv("TRUTHCAST_PLATFORM_KUAISHOU_MAX_SEC", "90"))
PLATFORM_BILIBILI_MAX_SEC = int(os.getenv("TRUTHCAST_PLATFORM_BILIBILI_MAX_SEC", "180"))


# 平台配置
PLATFORM_CONFIGS = {
    Platform.WEIBO: {
        "name": "微博",
        "max_length": PLATFORM_WEIBO_MAX,
        "features": ["话题标签", "转发友好", "口语化"],
        "tips": ["最佳发布时间：工作日早8-9点或晚8-10点", "建议配图1-3张", "积极回复评论增加互动"],
    },
    Platform.WECHAT: {
        "name": "微信公众号",
        "max_length": PLATFORM_WECHAT_MAX,
        "features": ["排版友好", "可插入引用", "图文并茂"],
        "tips": ["标题建议使用疑问句或数字", "正文分段清晰", "配图建议3-5张"],
    },
    Platform.SHORT_VIDEO: {
        "name": "短视频口播",
        "max_length": 90,  # 秒
        "features": ["开头吸引", "核心信息", "结尾互动"],
        "tips": ["开头3秒抓眼球", "字幕清晰易读", "BGM选择合适"],
    },
    Platform.NEWS: {
        "name": "新闻通稿",
        "max_length": 800,
        "features": ["倒金字塔结构", "正式客观", "可引用权威"],
        "tips": ["标题简洁有力", "导语包含核心信息", "可联系权威媒体"],
    },
    Platform.OFFICIAL: {
        "name": "官方声明",
        "max_length": 600,
        "features": ["正式严谨", "标题正文落款", "法律合规"],
        "tips": ["需经法务审核", "落款需盖章", "保留签发记录"],
    },
    Platform.XIAOHONGSHU: {
        "name": "小红书",
        "max_length": PLATFORM_XIAOHONGSHU_MAX,
        "features": ["标题吸引", "emoji适当", "种草风/分享风"],
        "tips": ["标题可用疑问句或数字开头", "配图建议精美封面", "标签3-5个"],
    },
    Platform.DOUYIN: {
        "name": "抖音",
        "max_length": PLATFORM_DOUYIN_MAX_SEC,
        "features": ["开头3秒抓眼球", "快节奏", "情绪饱满"],
        "tips": ["开头前3秒最重要", "BGM选择热门音乐", "字幕大且清晰"],
    },
    Platform.KUAISHOU: {
        "name": "快手",
        "max_length": PLATFORM_KUAISHOU_MAX_SEC,
        "features": ["接地气", "亲切", "互动引导强"],
        "tips": ["开头可用提问吸引", "结尾引导评论", "画面自然真实"],
    },
    Platform.BILIBILI: {
        "name": "B站",
        "max_length": PLATFORM_BILIBILI_MAX_SEC,
        "features": ["专业深度", "可引用数据", "2-3分钟"],
        "tips": ["开头设置悬念", "可引用数据来源", "弹幕互动点设计"],
    },
}


def _get_platform_requirements(platforms: list[Platform]) -> str:
    """获取平台要求描述"""
    lines = []
    for i, p in enumerate(platforms, 1):
        config = PLATFORM_CONFIGS.get(p, {})
        lines.append(f"{i}. {config.get('name', p.value)} ({p.value}):")
        if "max_length" in config:
            if p in [Platform.DOUYIN, Platform.KUAISHOU, Platform.BILIBILI, Platform.SHORT_VIDEO]:
                lines.append(f"   - 时长: {config['max_length']}秒以内")
            else:
                lines.append(f"   - 字数: {config['max_length']}字以内")
        if config.get("features"):
            lines.append(f"   - 特点: {', '.join(config['features'])}")
        if config.get("tips"):
            lines.append(f"   - 发布建议: {config['tips'][0]}")
    return "\n".join(lines)


def _record_trace(stage: str, payload: dict[str, Any]) -> None:
    """记录 debug trace"""
    if not DEBUG_CONTENT:
        return
    
    try:
        current_file = os.path.abspath(__file__)
        services_dir = os.path.dirname(current_file)
        content_dir = os.path.dirname(services_dir)
        app_dir = os.path.dirname(content_dir)
        project_root = os.path.dirname(app_dir)
        
        debug_dir = os.path.join(project_root, "debug")
        os.makedirs(debug_dir, exist_ok=True)
        trace_file = os.path.join(debug_dir, "content_trace.jsonl")
        
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "module": "platform_scripts",
            "stage": stage,
            "payload": serialize_for_json(payload),
        }
        with open(trace_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.error("写入 content trace 失败: %s", exc)


async def _call_llm(prompt: str) -> dict | None:
    """调用 LLM 生成平台话术"""
    if not CONTENT_LLM_ENABLED or not CONTENT_LLM_API_KEY:
        logger.info("[PlatformScripts] LLM not enabled or no API key")
        return None
    
    headers = {
        "Authorization": f"Bearer {CONTENT_LLM_API_KEY}",
        "Content-Type": "application/json",
    }
    
    system_prompt = "你是新媒体运营专家，擅长针对不同平台生成适配的发布话术。输出必须为严格的 JSON 格式。"
    user_prompt = prompt

    payload = {
        "model": CONTENT_LLM_MODEL or "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 8000,
    }
    
    _record_trace(
        "llm_request",
        {
            "base_url": CONTENT_LLM_BASE_URL,
            "model": payload.get("model"),
            "temperature": payload.get("temperature"),
            "max_tokens": payload.get("max_tokens"),
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
        },
    )
    
    try:
        async with httpx.AsyncClient(timeout=CONTENT_TIMEOUT_SEC) as client:
            response = await client.post(
                f"{CONTENT_LLM_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            result = safe_json_loads(content)
            _record_trace(
                "llm_response",
                {
                    "raw_content": content,
                    "result": result,
                },
            )
            return result
    except Exception as exc:
        logger.error("[PlatformScripts] LLM 调用失败: %s", exc)
        _record_trace("llm_error", {"error": str(exc)})
        return None


def _fallback_platform_script(
    platform: Platform,
    clarification: ClarificationContent,
    report: ReportResponse,
) -> PlatformScript:
    """规则兜底生成平台话术"""
    config = PLATFORM_CONFIGS.get(platform, {})
    
    if platform == Platform.WEIBO:
        content = clarification.short[:PLATFORM_WEIBO_MAX]
        return PlatformScript(
            platform=platform,
            content=content,
            tips=config.get("tips", []),
            hashtags=["#真相来了", "#辟谣"],
            estimated_read_time="30秒",
        )
    
    elif platform == Platform.WECHAT:
        content = clarification.long[:PLATFORM_WECHAT_MAX]
        return PlatformScript(
            platform=platform,
            content=content,
            tips=config.get("tips", []),
            estimated_read_time="2分钟",
        )
    
    elif platform == Platform.SHORT_VIDEO:
        content = f"【辟谣提醒】{clarification.short}\n\n{clarification.medium}"
        return PlatformScript(
            platform=platform,
            content=content,
            tips=config.get("tips", []),
            estimated_read_time="60秒",
        )
    
    elif platform == Platform.NEWS:
        content = f"【新闻通稿】\n\n{clarification.long}"
        return PlatformScript(
            platform=platform,
            content=content,
            tips=config.get("tips", []),
            estimated_read_time="3分钟",
        )
    
    elif platform == Platform.OFFICIAL:
        content = f"【官方声明】\n\n{clarification.long}\n\n特此声明。"
        return PlatformScript(
            platform=platform,
            content=content,
            tips=config.get("tips", []),
            estimated_read_time="2分钟",
        )
    
    elif platform == Platform.XIAOHONGSHU:
        content = f"🔍 真相来了！\n\n{clarification.medium[:PLATFORM_XIAOHONGSHU_MAX]}\n\n#真相 #辟谣"
        return PlatformScript(
            platform=platform,
            content=content,
            tips=config.get("tips", []),
            estimated_read_time="1分钟",
        )
    
    elif platform == Platform.DOUYIN:
        content = f"【开头】这个消息是真的吗？\n【正文】{clarification.short}\n【结尾】关注官方信息，不信谣不传谣！"
        return PlatformScript(
            platform=platform,
            content=content,
            tips=config.get("tips", []),
            estimated_read_time=f"{PLATFORM_DOUYIN_MAX_SEC}秒",
        )
    
    elif platform == Platform.KUAISHOU:
        content = f"【开头】有人问你这个问题怎么回？\n【正文】{clarification.short}\n【结尾】评论区告诉我你怎么看？"
        return PlatformScript(
            platform=platform,
            content=content,
            tips=config.get("tips", []),
            estimated_read_time=f"{PLATFORM_KUAISHOU_MAX_SEC}秒",
        )
    
    elif platform == Platform.BILIBILI:
        content = f"【开头】今天我们来聊聊这件事...\n\n{clarification.long}\n\n【结尾】你怎么看？欢迎弹幕讨论！"
        return PlatformScript(
            platform=platform,
            content=content,
            tips=config.get("tips", []),
            estimated_read_time=f"{PLATFORM_BILIBILI_MAX_SEC}秒",
        )
    
    else:
        return PlatformScript(
            platform=platform,
            content=clarification.medium,
            tips=[],
            estimated_read_time="1分钟",
        )


async def generate_platform_scripts(
    clarification: ClarificationContent,
    report: ReportResponse,
    simulation: SimulateResponse | None,
    platforms: list[Platform],
) -> list[PlatformScript]:
    """
    生成多平台话术
    
    Args:
        clarification: 澄清稿
        report: 检测报告
        simulation: 舆情预演结果
        platforms: 目标平台列表
        
    Returns:
        list[PlatformScript]: 平台话术列表
    """
    logger.info("[PlatformScripts] 开始生成多平台话术, 平台数=%d", len(platforms))
    
    platform_requirements = _get_platform_requirements(platforms)
    
    prompt = f"""你是新媒体运营专家，需要针对以下澄清稿生成多平台适配话术。

【澄清稿基础内容】
短版（约100字）：
{clarification.short}

中版（约300字）：
{clarification.medium}

长版（约600字）：
{clarification.long}

【风险信息】
- 风险等级: {report.risk_level}
- 场景: {report.detected_scenario}

【目标平台】
{platform_requirements}

【输出要求】
为每个平台生成适配话术，输出 JSON 格式：
{{
  "scripts": [
    {{
      "platform": "weibo",
      "content": "微博正文...",
      "tips": ["发布建议1", "发布建议2"],
      "hashtags": ["#话题1", "#话题2"]
    }},
    {{
      "platform": "xiaohongshu",
      "content": "小红书正文...",
      "tips": ["发布建议1"],
      "hashtags": null
    }},
    {{
      "platform": "douyin",
      "content": "抖音口播脚本...",
      "tips": ["BGM建议", "字幕建议"],
      "hashtags": null
    }}
  ]
}}

注意：
1. 微博必须包含 hashtags 字段（2-3个话题标签）
2. 视频平台（抖音/快手/B站/短视频）的 content 应该是口播脚本格式
3. tips 字段给出具体的发布建议
"""
    
    # 尝试 LLM 生成
    result = await _call_llm(prompt)
    
    if result and "scripts" in result:
        scripts = []
        platform_map = {p.value: p for p in platforms}
        
        for item in result["scripts"]:
            platform_str = item.get("platform", "")
            platform = platform_map.get(platform_str)
            if platform:
                scripts.append(PlatformScript(
                    platform=platform,
                    content=item.get("content", ""),
                    tips=item.get("tips", []),
                    hashtags=item.get("hashtags"),
                    estimated_read_time=None,
                ))
        
        # 补充缺失的平台
        existing_platforms = {s.platform for s in scripts}
        for p in platforms:
            if p not in existing_platforms:
                scripts.append(_fallback_platform_script(p, clarification, report))
        
        if scripts:
            return scripts
    
    # 回退到规则生成
    logger.info("[PlatformScripts] 使用规则兜底生成")
    return [_fallback_platform_script(p, clarification, report) for p in platforms]
