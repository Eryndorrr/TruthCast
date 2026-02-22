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
    feedback_status: str | None = None
    feedback_note: str | None = None


class HistoryFeedbackRequest(BaseModel):
    status: str = Field(pattern="^(accurate|inaccurate|evidence_irrelevant)$")
    note: str | None = None
