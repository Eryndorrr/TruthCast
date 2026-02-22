import axios from 'axios';
import type {
  ClaimItem,
  ContentGenerateRequest,
  ContentGenerateResponse,
  ContentDraft,
  DetectResponse,
  EvidenceItem,
  HistoryDetail,
  HistoryItem,
  ReportResponse,
  SimulateResponse,
  StrategyConfig,
} from '@/types';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? 'http://127.0.0.1:8000';

const api = axios.create({
  baseURL: API_BASE,
  headers: { 'Content-Type': 'application/json' },
});

export async function detect(text: string): Promise<DetectResponse> {
  const { data } = await api.post<DetectResponse>('/detect', { text });
  return data;
}

export async function detectClaims(text: string, strategy?: StrategyConfig | null): Promise<ClaimItem[]> {
  const { data } = await api.post<{ claims: ClaimItem[] }>('/detect/claims', { text, strategy });
  return data.claims;
}

export async function detectEvidence(
  text: string,
  claims: ClaimItem[],
  strategy?: StrategyConfig | null
): Promise<EvidenceItem[]> {
  const { data } = await api.post<{ evidences: EvidenceItem[] }>('/detect/evidence', {
    text,
    claims,
    strategy,
  });
  return data.evidences;
}

export interface DetectReportResult {
  record_id: string;
  risk_score: number;
  risk_level: string;
  risk_label: string;
  detected_scenario: string;
  evidence_domains: string[];
  summary: string;
  suspicious_points: string[];
  claim_reports: Array<{
    claim: ClaimItem;
    evidences: EvidenceItem[];
    final_stance: string;
    notes: string[];
  }>;
}

export async function alignEvidence(
  claims: ClaimItem[],
  evidences: EvidenceItem[],
  strategy?: StrategyConfig | null
): Promise<EvidenceItem[]> {
  const { data } = await api.post<{ evidences: EvidenceItem[] }>('/detect/evidence/align', {
    claims,
    evidences,
    strategy,
  });
  return data.evidences;
}

export async function detectReport(
  text: string,
  claims?: ClaimItem[],
  evidences?: EvidenceItem[],
  detectData?: DetectResponse | null,
  strategy?: StrategyConfig | null
): Promise<DetectReportResult> {
  const { data } = await api.post<DetectReportResult>('/detect/report', {
    text,
    claims,
    evidences,
    detect_data: detectData,
    strategy,
  });
  return data;
}

export async function simulate(
  text: string,
  claims?: ClaimItem[],
  evidences?: EvidenceItem[],
  report?: ReportResponse
): Promise<SimulateResponse> {
  const { data } = await api.post<SimulateResponse>('/simulate', {
    text,
    claims,
    evidences,
    report,
    time_window_hours: 24,
    platform: 'general',
    comments: [],
  });
  return data;
}

export type SimulationStage = 'emotion' | 'narratives' | 'flashpoints' | 'suggestion';

export interface SimulationStreamEvent {
  stage: SimulationStage;
  data: Partial<SimulateResponse>;
}

export async function simulateStream(
  text: string,
  onStage: (event: SimulationStreamEvent) => void,
  claims?: ClaimItem[],
  evidences?: EvidenceItem[],
  report?: ReportResponse
): Promise<void> {
  const response = await fetch(`${API_BASE}/simulate/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      text,
      claims,
      evidences,
      report,
      time_window_hours: 24,
      platform: 'general',
      comments: [],
    }),
  });

  if (!response.ok) {
    throw new Error(`Simulation stream failed: ${response.status}`);
  }

  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error('No response body');
  }

  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try {
          const event = JSON.parse(line.slice(6)) as SimulationStreamEvent;
          onStage(event);
        } catch {
          console.warn('Failed to parse SSE event:', line);
        }
      }
    }
  }
}

export async function getHistory(limit = 20): Promise<HistoryItem[]> {
  const { data } = await api.get<{ items: HistoryItem[] }>(`/history?limit=${limit}`);
  return data.items;
}

export async function getHistoryDetail(recordId: string): Promise<HistoryDetail> {
  const { data } = await api.get<HistoryDetail>(`/history/${recordId}`);
  return data;
}

export async function submitHistoryFeedback(
  recordId: string,
  status: 'accurate' | 'inaccurate' | 'evidence_irrelevant',
  note = ''
): Promise<void> {
  await api.post(`/history/${recordId}/feedback`, { status, note });
}

export async function updateHistorySimulation(
  recordId: string,
  simulation: SimulateResponse
): Promise<void> {
  await api.post(`/history/${recordId}/simulation`, simulation);
}

export async function updateHistoryContent(
  recordId: string,
  content: ContentDraft
): Promise<void> {
  await api.post(`/history/${recordId}/content`, content);
}

// ========== 应对内容生成 API ==========

export async function generateContent(
  request: ContentGenerateRequest
): Promise<ContentGenerateResponse> {
  const { data } = await api.post<ContentGenerateResponse>('/content/generate', request);
  return data;
}

export async function generateClarification(
  request: ContentGenerateRequest
): Promise<ContentGenerateResponse['clarification']> {
  const { data } = await api.post<ContentGenerateResponse['clarification']>('/content/clarification', request);
  return data;
}

export async function generateFAQ(
  request: ContentGenerateRequest
): Promise<ContentGenerateResponse['faq']> {
  const { data } = await api.post<ContentGenerateResponse['faq']>('/content/faq', request);
  return data;
}

export async function generatePlatformScripts(
  request: ContentGenerateRequest
): Promise<ContentGenerateResponse['platform_scripts']> {
  const { data } = await api.post<ContentGenerateResponse['platform_scripts']>('/content/platform-scripts', request);
  return data;
}
