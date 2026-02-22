from __future__ import annotations

from pydantic import BaseModel, Field


class StrategyConfig(BaseModel):
    max_claims: int = Field(default=5, ge=1, le=20, description="最大主张抽取数量")
    complexity_level: str = Field(default="medium", description="文本复杂度: simple/medium/complex")
    complexity_reason: str = Field(default="", description="复杂度判定理由")
    
    evidence_per_claim: int = Field(default=5, ge=1, le=10, description="每条主张最大证据检索数量")
    risk_level: str = Field(default="medium", description="风险级别: critical/high/medium/low")
    risk_reason: str = Field(default="", description="风险策略理由")
    
    summary_target_min: int = Field(default=1, ge=1, description="证据聚合目标最小数量")
    summary_target_max: int = Field(default=5, ge=1, description="证据聚合目标最大数量")
    enable_summarization: bool = Field(default=True, description="是否启用证据聚合")


class DetectRequest(BaseModel):
    text: str = Field(min_length=5, description="News content to analyze")


class DetectResponse(BaseModel):
    label: str
    confidence: float
    score: int
    reasons: list[str]
    strategy: StrategyConfig | None = None
    truncated: bool = False


class ClaimItem(BaseModel):
    claim_id: str
    claim_text: str
    entity: str | None = None
    time: str | None = None
    location: str | None = None
    value: str | None = None
    source_sentence: str


class ClaimsRequest(BaseModel):
    text: str = Field(min_length=5)
    strategy: StrategyConfig | None = None


class ClaimsResponse(BaseModel):
    claims: list[ClaimItem]


class EvidenceItem(BaseModel):
    evidence_id: str
    claim_id: str
    title: str
    source: str
    url: str
    published_at: str
    summary: str
    stance: str
    source_weight: float = Field(ge=0.0, le=1.0)
    source_type: str = "local_kb"
    retrieved_at: str | None = None
    domain: str | None = None
    is_authoritative: bool | None = None
    raw_snippet: str | None = None
    alignment_rationale: str | None = None
    alignment_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    source_urls: list[str] | None = None


class EvidenceRequest(BaseModel):
    text: str | None = None
    claims: list[ClaimItem] | None = None
    strategy: StrategyConfig | None = None


class EvidenceResponse(BaseModel):
    evidences: list[EvidenceItem]


class EvidenceAlignRequest(BaseModel):
    claims: list[ClaimItem]
    evidences: list[EvidenceItem]
    strategy: StrategyConfig | None = None


class EvidenceAlignResponse(BaseModel):
    evidences: list[EvidenceItem]


class ClaimReportItem(BaseModel):
    claim: ClaimItem
    evidences: list[EvidenceItem]
    final_stance: str
    notes: list[str]


class ReportRequest(BaseModel):
    text: str | None = None
    claims: list[ClaimItem] | None = None
    evidences: list[EvidenceItem] | None = None
    detect_data: DetectResponse | None = None
    strategy: StrategyConfig | None = None


class ReportResponse(BaseModel):
    risk_score: int = Field(ge=0, le=100)
    risk_level: str
    risk_label: str
    detected_scenario: str
    evidence_domains: list[str]
    summary: str
    suspicious_points: list[str]
    claim_reports: list[ClaimReportItem]


class SimulateRequest(BaseModel):
    text: str = Field(min_length=5)
    claims: list[ClaimItem] | None = None
    evidences: list[EvidenceItem] | None = None
    report: ReportResponse | None = None
    time_window_hours: int = Field(default=24, ge=1, le=168)
    platform: str = "general"
    comments: list[str] = Field(default_factory=list)


class NarrativeItem(BaseModel):
    title: str
    stance: str
    probability: float = Field(ge=0.0, le=1.0)
    trigger_keywords: list[str]
    sample_message: str


class TimelineItem(BaseModel):
    hour: int
    event: str
    expected_reach: str


class ActionItem(BaseModel):
    priority: str = Field(description="优先级: urgent/high/medium")
    category: str = Field(description="类别: official/media/platform/user")
    action: str = Field(description="具体行动")
    timeline: str = Field(description="建议时间")
    responsible: str | None = Field(default=None, description="责任方")


class SuggestionData(BaseModel):
    summary: str = Field(description="综合建议摘要")
    actions: list[ActionItem] = Field(default_factory=list, description="行动清单")


class SimulateResponse(BaseModel):
    emotion_distribution: dict[str, float]
    stance_distribution: dict[str, float]
    narratives: list[NarrativeItem]
    flashpoints: list[str]
    suggestion: SuggestionData
    timeline: list[TimelineItem] | None = None
    emotion_drivers: list[str] | None = None
    stance_drivers: list[str] | None = None


class HistoryItem(BaseModel):
    id: str
    created_at: str
    input_preview: str
    risk_label: str
    risk_score: int
    detected_scenario: str
    evidence_domains: list[str]
    feedback_status: str | None = None


class HistoryListResponse(BaseModel):
    items: list[HistoryItem]


class HistoryDetailResponse(BaseModel):
    id: str
    created_at: str
    input_text: str
    risk_label: str
    risk_score: int
    detected_scenario: str
    evidence_domains: list[str]
    report: ReportResponse
    detect_data: DetectResponse | None = None
    simulation: SimulateResponse | None = None
    content: ContentDraftData | None = None
    feedback_status: str | None = None
    feedback_note: str | None = None


class HistoryFeedbackRequest(BaseModel):
    status: str = Field(pattern="^(accurate|inaccurate|evidence_irrelevant)$")
    note: str | None = None


# ========== 应对内容生成 Schema ==========

from enum import Enum


class ClarificationStyle(str, Enum):
    """澄清稿风格"""
    FORMAL = "formal"      # 正式严肃
    FRIENDLY = "friendly"  # 亲切友好
    NEUTRAL = "neutral"    # 中性客观


class Platform(str, Enum):
    """发布平台"""
    WEIBO = "weibo"              # 微博
    WECHAT = "wechat"            # 微信公众号
    SHORT_VIDEO = "short_video"  # 短视频口播（通用）
    NEWS = "news"                # 新闻通稿
    OFFICIAL = "official"        # 官方声明
    XIAOHONGSHU = "xiaohongshu"  # 小红书
    DOUYIN = "douyin"            # 抖音
    KUAISHOU = "kuaishou"        # 快手
    BILIBILI = "bilibili"        # B站


class FAQItem(BaseModel):
    """FAQ 条目"""
    question: str = Field(description="问题")
    answer: str = Field(description="回答")
    category: str = Field(default="general", description="分类: core/detail/background")


class ClarificationContent(BaseModel):
    """澄清稿内容"""
    short: str = Field(description="短版本，约100字")
    medium: str = Field(description="中版本，约300字")
    long: str = Field(description="长版本，约600字")


class PlatformScript(BaseModel):
    """平台话术"""
    platform: Platform
    content: str = Field(description="话术内容")
    tips: list[str] = Field(default_factory=list, description="发布建议")
    hashtags: list[str] | None = Field(default=None, description="推荐标签，微博专用")
    estimated_read_time: str | None = Field(default=None, description="预计阅读时长")


class ContentGenerateRequest(BaseModel):
    """应对内容生成请求"""
    text: str = Field(description="原始新闻文本")
    report: ReportResponse = Field(description="检测报告")
    simulation: SimulateResponse | None = Field(default=None, description="舆情预演结果")
    clarification: ClarificationContent | None = Field(
        default=None,
        description="可选：已生成澄清稿（用于复用，避免多平台话术/FAQ 重复生成澄清稿）",
    )
    
    # 可选参数
    style: ClarificationStyle = Field(default=ClarificationStyle.NEUTRAL, description="澄清稿风格")
    platforms: list[Platform] = Field(
        default_factory=lambda: [Platform.WEIBO, Platform.WECHAT, Platform.SHORT_VIDEO],
        description="目标平台"
    )
    include_faq: bool = Field(default=True, description="是否生成FAQ")
    faq_count: int = Field(default=5, ge=3, le=10, description="FAQ条目数量")


class ContentGenerateResponse(BaseModel):
    """应对内容生成响应"""
    clarification: ClarificationContent = Field(description="澄清稿")
    faq: list[FAQItem] | None = Field(default=None, description="FAQ列表")
    platform_scripts: list[PlatformScript] = Field(description="多平台话术")
    
    # 元数据
    generated_at: str = Field(description="生成时间")
    based_on: dict = Field(description="生成依据摘要")


class ContentDraftData(BaseModel):
    """用于历史记录/局部更新的应对内容草稿数据（允许分模块逐步写入）"""

    clarification: ClarificationContent | None = None
    # 澄清稿多风格/多版本列表（前端增量生成时写入）
    clarifications: list[dict] | None = None
    primary_clarification_id: str | None = None
    faq: list[FAQItem] | None = None
    platform_scripts: list[PlatformScript] | None = None
    generated_at: str | None = None
    based_on: dict | None = None
