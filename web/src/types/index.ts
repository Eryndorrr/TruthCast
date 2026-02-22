export type StrategyConfig = {
  max_claims: number;
  complexity_level: string;
  complexity_reason: string;
  evidence_per_claim: number;
  risk_level: string;
  risk_reason: string;
  summary_target_min: number;
  summary_target_max: number;
  enable_summarization: boolean;
};

export type DetectResponse = {
  label: string;
  confidence: number;
  score: number;
  reasons: string[];
  strategy?: StrategyConfig | null;
  truncated?: boolean;
};

export type ClaimItem = {
  claim_id: string;
  claim_text: string;
  entity?: string | null;
  time?: string | null;
  location?: string | null;
  value?: string | null;
  source_sentence: string;
};

export type EvidenceItem = {
  evidence_id: string;
  claim_id: string;
  title: string;
  source: string;
  url: string;
  published_at: string;
  summary: string;
  stance: string;
  source_weight: number;
  source_type?: string;
  retrieved_at?: string | null;
  domain?: string | null;
  is_authoritative?: boolean | null;
  raw_snippet?: string | null;
  alignment_rationale?: string | null;
  alignment_confidence?: number | null;
  source_urls?: string[];
};

export type ClaimReport = {
  claim: ClaimItem;
  evidences: EvidenceItem[];
  final_stance: string;
  notes: string[];
};

export type ReportResponse = {
  risk_score: number;
  risk_level: string;
  risk_label: string;
  detected_scenario: string;
  evidence_domains: string[];
  summary: string;
  suspicious_points: string[];
  claim_reports: ClaimReport[];
};

export type NarrativeItem = {
  title: string;
  stance: string;
  probability: number;
  trigger_keywords: string[];
  sample_message: string;
};

export type TimelineItem = {
  hour: number;
  event: string;
  expected_reach: string;
};

export type ActionItem = {
  priority: 'urgent' | 'high' | 'medium';
  category: 'official' | 'media' | 'platform' | 'user';
  action: string;
  timeline: string;
  responsible?: string;
};

export type SuggestionData = {
  summary: string;
  actions: ActionItem[];
};

export type SimulateResponse = {
  emotion_distribution: Record<string, number>;
  stance_distribution: Record<string, number>;
  narratives: NarrativeItem[];
  flashpoints: string[];
  suggestion: SuggestionData;
  timeline?: TimelineItem[];
  emotion_drivers?: Record<string, string[]>;
  stance_drivers?: Record<string, string[]>;
};

export type HistoryItem = {
  id: string;
  created_at: string;
  input_preview: string;
  risk_label: string;
  risk_score: number;
  detected_scenario: string;
  evidence_domains: string[];
  feedback_status?: string | null;
};

export type HistoryDetail = {
  id: string;
  created_at: string;
  input_text: string;
  risk_label: string;
  risk_score: number;
  detected_scenario: string;
  evidence_domains: string[];
  report: ReportResponse;
  detect_data?: DetectResponse | null;
  simulation?: SimulateResponse | null;
  feedback_status?: string | null;
  feedback_note?: string | null;
};

export type Phase = 'detect' | 'claims' | 'evidence' | 'report' | 'simulation';
export type PhaseStatus = 'idle' | 'running' | 'done' | 'failed';
