import { create } from 'zustand';
import { toast } from 'sonner';
import type {
  ClaimItem,
  ContentDraft,
  DetectResponse,
  EvidenceItem,
  Phase,
  PhaseStatus,
  PhaseState,
  ReportResponse,
  SimulateResponse,
  HistoryDetail,
  StrategyConfig,
} from '@/types';
import {
  alignEvidence,
  detect,
  detectClaims,
  detectEvidence,
  detectReport,
  simulateStream,
  updateHistorySimulation,
} from '@/services/api';
import type { SimulationStreamEvent } from '@/services/api';

interface PipelineState {
  text: string;
  error: string | null;
  detectData: DetectResponse | null;
  strategy: StrategyConfig | null;
  claims: ClaimItem[];
  rawEvidences: EvidenceItem[];
  evidences: EvidenceItem[];
  report: ReportResponse | null;
  simulation: SimulateResponse | null;
  // 内容生成允许"逐步生成"，因此使用 ContentDraft 保存阶段性结果
  content: ContentDraft | null;
  phases: PhaseState;
  isFromHistory: boolean;
  recordId: string | null;
  
  setText: (text: string) => void;
  setPhase: (phase: Phase, status: PhaseStatus) => void;
  setError: (error: string | null) => void;
  setContent: (content: ContentDraft | null) => void;
  runPipeline: () => Promise<void>;
  retryPhase: (phase: Phase) => Promise<void>;
  retryFailed: () => Promise<void>;
  loadFromHistory: (detail: HistoryDetail, simulation?: SimulateResponse | null) => void;
  reset: () => void;
}

const INIT_PHASE_STATE: PhaseState = {
  detect: 'idle',
  claims: 'idle',
  evidence: 'idle',
  report: 'idle',
  simulation: 'idle',
  content: 'idle',
};

const initialState = {
  text: '网传某事件"100%真实且必须立刻转发"，消息来源为内部人士，请快速核查其真实性风险。',
  error: null,
  detectData: null as DetectResponse | null,
  strategy: null as StrategyConfig | null,
  claims: [] as ClaimItem[],
  rawEvidences: [] as EvidenceItem[],
  evidences: [] as EvidenceItem[],
  report: null as ReportResponse | null,
  simulation: null as SimulateResponse | null,
  content: null as ContentDraft | null,
  phases: INIT_PHASE_STATE,
  isFromHistory: false,
  recordId: null as string | null,
};

export const usePipelineStore = create<PipelineState>((set, get) => ({
  ...initialState,

  setText: (text) => set({ text }),
  
  setPhase: (phase, status) =>
    set((state) => ({
      phases: { ...state.phases, [phase]: status },
    })),

  setError: (error) => set({ error }),

  setContent: (content) => set({ content }),

  reset: () => set(initialState),

  runPipeline: async () => {
    const { text, setPhase, setError } = get();
    
    set({
      error: null,
      detectData: null,
      strategy: null,
      claims: [],
      rawEvidences: [],
      evidences: [],
      report: null,
      simulation: null,
      content: null,
      phases: INIT_PHASE_STATE,
      recordId: null,
      // 从历史记录回放后再发起新的分析时，必须重置该标记；否则会导致后续写回历史（content/simulation 等）被误拦截
      isFromHistory: false,
    });

    toast.info('开始分析...');

    const pushError = (message: string, showToast = true) => {
      setError(message);
      if (showToast) {
        toast.error(message);
      }
    };

    setPhase('detect', 'running');
    const detectPromise = detect(text)
      .then((result) => {
        set({ detectData: result, strategy: result.strategy ?? null });
        setPhase('detect', 'done');
        toast.success('风险快照完成');
        if (result.truncated) {
          toast.warning('输入文本较长，已自动截断至 8000 字符以内进行分析');
        }
      })
      .catch((err) => {
        setPhase('detect', 'failed');
        pushError(`风险快照失败：${err instanceof Error ? err.message : '未知错误'}`);
      });

    const deepScanPromise = (async () => {
      // Wait for detect to complete to get strategy
      await detectPromise;
      const currentStrategy = get().strategy;
      
      try {
        setPhase('claims', 'running');
        const claimsResult = await detectClaims(text, currentStrategy);
        set({ claims: claimsResult });
        setPhase('claims', 'done');
        toast.success(`主张抽取完成，共 ${claimsResult.length} 条`);

        setPhase('evidence', 'running');
        let evidenceResult: EvidenceItem[] = [];
        try {
          // Step 1: 证据检索
          const rawEvidences = await detectEvidence(text, claimsResult, currentStrategy);
          set({ rawEvidences });
          toast.success(`证据检索完成，共 ${rawEvidences.length} 条`);
          
          // Step 2: 证据聚合与对齐
          evidenceResult = await alignEvidence(claimsResult, rawEvidences, currentStrategy);
          set({ evidences: evidenceResult });
          setPhase('evidence', 'done');
          toast.success(`证据聚合对齐完成，共 ${evidenceResult.length} 条`);
        } catch (err) {
          setPhase('evidence', 'failed');
          pushError(`证据处理失败：${err instanceof Error ? err.message : '未知错误'}`);
        }

        let reportResult: ReportResponse | null = null;
        let recordId: string | null = null;
        setPhase('report', 'running');
        try {
          const currentDetectData = get().detectData;
          const reportResponse = await detectReport(text, claimsResult, evidenceResult, currentDetectData, currentStrategy);
          recordId = reportResponse.record_id;
          reportResult = {
            risk_score: reportResponse.risk_score,
            risk_level: reportResponse.risk_level,
            risk_label: reportResponse.risk_label,
            detected_scenario: reportResponse.detected_scenario,
            evidence_domains: reportResponse.evidence_domains,
            summary: reportResponse.summary,
            suspicious_points: reportResponse.suspicious_points,
            claim_reports: reportResponse.claim_reports,
          };
          set({ report: reportResult, recordId });
          setPhase('report', 'done');
          toast.success('综合报告生成完成');
        } catch (err) {
          setPhase('report', 'failed');
          pushError(`综合报告失败：${err instanceof Error ? err.message : '未知错误'}`);
        }

        setPhase('simulation', 'running');
        try {
          await simulateStream(
            text,
            (event: SimulationStreamEvent) => {
              console.log('[Simulation Stream] Received event:', event.stage, event.data);
              const currentSimulation = get().simulation || {
                emotion_distribution: {},
                stance_distribution: {},
                narratives: [],
                flashpoints: [],
                suggestion: '',
                timeline: [],
              };

              const updatedSimulation = {
                ...currentSimulation,
                ...event.data,
              } as SimulateResponse;

              console.log('[Simulation Stream] Updated simulation:', updatedSimulation);
              set({ simulation: updatedSimulation });

              const stageMessages: Record<string, string> = {
                emotion: '情绪与立场分析完成',
                narratives: '叙事分支生成完成',
                flashpoints: '引爆点识别完成',
                suggestion: '应对建议生成完成',
              };
              toast.success(stageMessages[event.stage] || `${event.stage} 完成`);
            },
            claimsResult,
            evidenceResult,
            reportResult ?? undefined
          );
          setPhase('simulation', 'done');
          toast.success('舆情预演完成');
          
          const finalSimulation = get().simulation;
          if (recordId && finalSimulation) {
            try {
              await updateHistorySimulation(recordId, finalSimulation);
            } catch (err) {
              console.warn('Failed to update simulation to history:', err);
            }
          }
          
          toast.success('分析完成');
        } catch (err) {
          setPhase('simulation', 'failed');
          pushError(`舆情预演失败：${err instanceof Error ? err.message : '未知错误'}`);
        }
      } catch (err) {
        setPhase('claims', 'failed');
        setPhase('evidence', 'idle');
        setPhase('report', 'idle');
        setPhase('simulation', 'idle');
        pushError(`主张抽取失败：${err instanceof Error ? err.message : '未知错误'}`);
      }
    })();

    await Promise.allSettled([detectPromise, deepScanPromise]);
  },

  loadFromHistory: (detail: HistoryDetail, simulation?: SimulateResponse | null) => {
    const claims: ClaimItem[] = detail.report.claim_reports.map((cr) => cr.claim);
    
    const evidences: EvidenceItem[] = [];
    const seenEvidenceIds = new Set<string>();
    for (const cr of detail.report.claim_reports) {
      for (const ev of cr.evidences) {
        if (!seenEvidenceIds.has(ev.evidence_id)) {
          evidences.push(ev);
          seenEvidenceIds.add(ev.evidence_id);
        }
      }
    }

    const donePhases: PhaseState = {
      detect: detail.detect_data ? 'done' : 'idle',
      claims: 'done',
      evidence: 'done',
      report: 'done',
      simulation: (simulation || detail.simulation) ? 'done' : 'idle',
      content: 'idle',
    };

    if (detail.content) {
      donePhases.content = 'done';
    }

    set({
      text: detail.input_text,
      error: null,
      detectData: detail.detect_data ?? null,
      claims,
      rawEvidences: evidences,
      evidences,
      report: detail.report,
      simulation: simulation ?? detail.simulation ?? null,
      content: detail.content ?? null,
      phases: donePhases,
      isFromHistory: true,
      recordId: detail.id,
    });
  },

  retryPhase: async (phase: Phase) => {
    const { text, setPhase, setError } = get();
    
    const phaseNames: Record<Phase, string> = {
      detect: '风险快照',
      claims: '主张抽取',
      evidence: '证据检索',
      report: '综合报告',
      simulation: '舆情预演',
      content: '应对内容',
    };

    // 不再清除下游数据，保留已完成的结果
    // 用户可手动选择是否重新运行后续阶段

    toast.info(`正在重试 ${phaseNames[phase]}...`);
    setPhase(phase, 'running');
    setError(null);

    try {
      switch (phase) {
        case 'detect':
          const detectResult = await detect(text);
          set({ detectData: detectResult, strategy: detectResult.strategy ?? null });
          setPhase('detect', 'done');
          toast.success('风险快照重试成功');
          break;

        case 'claims':
          const currentStrategy = get().strategy;
          const claimsResult = await detectClaims(text, currentStrategy);
          set({ claims: claimsResult });
          setPhase('claims', 'done');
          toast.success(`主张抽取重试成功，共 ${claimsResult.length} 条`);
          break;

        case 'evidence':
          // Step 1: 证据检索
          const evClaims = get().claims;
          const evStrategy = get().strategy;
          const rawEvidences = await detectEvidence(text, evClaims, evStrategy);
          set({ rawEvidences });
          toast.success(`证据检索完成，共 ${rawEvidences.length} 条`);
          
          // Step 2: 证据聚合与对齐
          const alignedEvidences = await alignEvidence(evClaims, rawEvidences, evStrategy);
          set({ evidences: alignedEvidences });
          setPhase('evidence', 'done');
          toast.success(`证据聚合对齐完成，共 ${alignedEvidences.length} 条`);
          break;

        case 'report':
          const reportClaims = get().claims;
          const reportEvidences = get().evidences;
          const reportDetectData = get().detectData;
          const reportStrategy = get().strategy;
          const reportResponse = await detectReport(text, reportClaims, reportEvidences, reportDetectData, reportStrategy);
          const newRecordId = reportResponse.record_id;
          const reportResult: ReportResponse = {
            risk_score: reportResponse.risk_score,
            risk_level: reportResponse.risk_level,
            risk_label: reportResponse.risk_label,
            detected_scenario: reportResponse.detected_scenario,
            evidence_domains: reportResponse.evidence_domains,
            summary: reportResponse.summary,
            suspicious_points: reportResponse.suspicious_points,
            claim_reports: reportResponse.claim_reports,
          };
          set({ report: reportResult, recordId: newRecordId });
          setPhase('report', 'done');
          toast.success('综合报告重试成功');
          break;

        case 'simulation':
          const simClaims = get().claims;
          const simEvidences = get().evidences;
          const simReport = get().report;
          
          await simulateStream(
            text,
            (event: SimulationStreamEvent) => {
              console.log('[Simulation Retry Stream] Received event:', event.stage, event.data);
              const currentSimulation = get().simulation || {
                emotion_distribution: {},
                stance_distribution: {},
                narratives: [],
                flashpoints: [],
                suggestion: '',
                timeline: [],
              };

              const updatedSimulation = {
                ...currentSimulation,
                ...event.data,
              } as SimulateResponse;

              set({ simulation: updatedSimulation });

              const stageMessages: Record<string, string> = {
                emotion: '情绪与立场分析完成',
                narratives: '叙事分支生成完成',
                flashpoints: '引爆点识别完成',
                suggestion: '应对建议生成完成',
              };
              toast.success(stageMessages[event.stage] || `${event.stage} 完成`);
            },
            simClaims,
            simEvidences,
            simReport ?? undefined
          );
          setPhase('simulation', 'done');
          toast.success('舆情预演重试成功');
          
          const retryRecordId = get().recordId;
          const finalSim = get().simulation;
          if (retryRecordId && finalSim) {
            try {
              await updateHistorySimulation(retryRecordId, finalSim);
            } catch (err) {
              console.warn('Failed to update simulation to history:', err);
            }
          }
          break;
      }
    } catch (err) {
      setPhase(phase, 'failed');
      const errorMsg = `${phaseNames[phase]}重试失败：${err instanceof Error ? err.message : '未知错误'}`;
      setError(errorMsg);
      toast.error(errorMsg);
    }
  },

  retryFailed: async () => {
    const { phases } = get();
    const phaseOrder: Phase[] = ['detect', 'claims', 'evidence', 'report', 'simulation'];
    
    for (const phase of phaseOrder) {
      if (phases[phase] === 'failed') {
        await get().retryPhase(phase);
        break;
      }
    }
  },
}));

export const useIsLoading = () =>
  usePipelineStore((state) =>
    Object.values(state.phases).some((status) => status === 'running')
  );

export const usePhaseLoading = (phase: Phase) =>
  usePipelineStore((state) => state.phases[phase] === 'running');
