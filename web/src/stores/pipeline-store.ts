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
  alignEvidenceWithSignal,
  detect,
  detectWithSignal,
  detectClaims,
  detectClaimsWithSignal,
  detectEvidence,
  detectEvidenceWithSignal,
  detectReport,
  detectReportWithSignal,
  simulateStream,
  loadLatestPipelineState,
  savePipelinePhaseSnapshot,
  updateHistorySimulation,
  detectUrl,
} from '@/services/api';
import type { SimulationStage, SimulationStreamEvent } from '@/services/api';

interface PipelineState {
  taskId: string | null;
  restorableTaskId: string | null;
  restorableUpdatedAt: string | null;
  text: string;
  error: string | null;
  detectData: DetectResponse | null;
  strategy: StrategyConfig | null;
  sourceMeta: {
    source_url?: string | null;
    source_title?: string | null;
    source_publish_date?: string | null;
  } | null;
  claims: ClaimItem[];
  rawEvidences: EvidenceItem[];
  evidences: EvidenceItem[];
  report: ReportResponse | null;
  simulation: SimulateResponse | null;
  simulationStage: string | null;
  simulationStageAt: string | null;
  // 内容生成允许"逐步生成"，因此使用 ContentDraft 保存阶段性结果
  content: ContentDraft | null;
  phases: PhaseState;
  abortController: AbortController | null;
  isFromHistory: boolean;
  recordId: string | null;
  setTaskId: (taskId: string | null) => void;
  setRestorable: (taskId: string | null, updatedAt?: string | null) => void;
  probeLatestRestorable: () => Promise<void>;
  
  setText: (text: string) => void;
  setPhase: (phase: Phase, status: PhaseStatus) => void;
  setError: (error: string | null) => void;
  setContent: (content: ContentDraft | null) => void;
  setSimulationStage: (stage: SimulationStage | null, at?: string | null) => void;
  hydrateFromLatest: (opts?: {
    taskId?: string | null;
    silent?: boolean;
    force?: boolean;
  }) => Promise<void>;
  runPipeline: (opts?: { taskId?: string | null }) => Promise<void>;
  interruptPipeline: () => void;
  retryPhase: (phase: Phase) => Promise<void>;
  retryFailed: () => Promise<void>;
  loadFromHistory: (detail: HistoryDetail, simulation?: SimulateResponse | null) => void;
  crawlUrl: (url: string) => Promise<void>;
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
  taskId: null as string | null,
  restorableTaskId: null as string | null,
  restorableUpdatedAt: null as string | null,
  text: '网传某事件"100%真实且必须立刻转发"，消息来源为内部人士，请快速核查其真实性风险。',
  error: null,
  detectData: null as DetectResponse | null,
  strategy: null as StrategyConfig | null,
  sourceMeta: null as {
    source_url?: string | null;
    source_title?: string | null;
    source_publish_date?: string | null;
  } | null,
  claims: [] as ClaimItem[],
  rawEvidences: [] as EvidenceItem[],
  evidences: [] as EvidenceItem[],
  report: null as ReportResponse | null,
  simulation: null as SimulateResponse | null,
  simulationStage: null as string | null,
  simulationStageAt: null as string | null,
  content: null as ContentDraft | null,
  phases: INIT_PHASE_STATE,
  abortController: null as AbortController | null,
  isFromHistory: false,
  recordId: null as string | null,
};

const DEFAULT_TEXT = initialState.text;

function _makeTaskId(): string {
  try {
    // 浏览器环境优先
    return crypto.randomUUID();
  } catch {
    // 兜底：时间戳 + 随机
    return `task_${Date.now()}_${Math.random().toString(16).slice(2)}`;
  }
}

function _phasePayload(get: () => PipelineState, phase: Phase): Record<string, unknown> | null {
  const s = get();
  switch (phase) {
    case 'detect':
      return {
        detectData: s.detectData,
        strategy: s.strategy,
        sourceMeta: s.sourceMeta,
      };
    case 'claims':
      return { claims: s.claims };
    case 'evidence':
      return {
        rawEvidences: s.rawEvidences,
        evidences: s.evidences,
      };
    case 'report':
      return {
        report: s.report,
        recordId: s.recordId,
        sourceMeta: s.sourceMeta,
      };
    case 'simulation':
      return { simulation: s.simulation };
    case 'content':
      return { content: s.content };
  }
}

async function _persistPhaseSnapshot(
  get: () => PipelineState,
  phase: Phase,
  status: PhaseStatus,
  opts?: {
    duration_ms?: number | null;
    error_message?: string | null;
    payload?: Record<string, unknown> | null;
  }
): Promise<void> {
  const s = get();
  const taskId = s.taskId;
  if (!taskId) return;

  try {
    await savePipelinePhaseSnapshot({
      task_id: taskId,
      input_text: s.text,
      phases: s.phases,
      phase,
      status,
      duration_ms: opts?.duration_ms ?? null,
      error_message: opts?.error_message ?? null,
      payload: opts?.payload ?? _phasePayload(get, phase),
      meta: {
        recordId: s.recordId,
      },
    });
  } catch (err) {
    // 持久化失败不应阻塞用户流程
    console.warn('[pipeline persistence] save-phase failed:', err);
  }
}

export const usePipelineStore = create<PipelineState>((set, get) => ({
  ...initialState,

  crawlUrl: async (url: string) => {
    const { setPhase, setError } = get();

    // 生成新的 AbortController 并重置状态 (类似 runPipeline)
    const controller = new AbortController();
    const signal = controller.signal;
    const taskId = _makeTaskId();

    set({
      taskId,
      text: '',
      error: null,
      detectData: null,
      strategy: null,
      sourceMeta: null,
      claims: [],
      rawEvidences: [],
      evidences: [],
      report: null,
      simulation: null,
      content: null,
      phases: INIT_PHASE_STATE,
      recordId: null,
      abortController: controller,
      isFromHistory: false,
    });

    toast.info('正在抓取链接内容...');
    setPhase('detect', 'running');
    void _persistPhaseSnapshot(get, 'detect', 'running', { payload: { url } });

    try {
      const result = await detectUrl(url, signal);
      if (!result.success) {
        throw new Error(result.error_msg || '抓取失败');
      }

      // 抓取成功，填充数据
      const title = (result.title || '').trim();
      const content = (result.content || '').trim();
      const mergedText = title ? `${title}\n\n${content}` : content;

      set({
        text: mergedText,
        detectData: result.risk,
        strategy: result.risk?.strategy ?? null,
        sourceMeta: {
          source_url: result.url,
          source_title: result.title,
          source_publish_date: result.publish_date,
        },
      });

      setPhase('detect', 'done');
      void _persistPhaseSnapshot(get, 'detect', 'done');
      toast.success('链接抓取与初步评估完成');

      // 抓取成功后，自动接续后续流水线
      // 调用 runPipeline({ taskId }) 确保全链路快照完整
      await get().runPipeline({ taskId });
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        setPhase('detect', 'canceled');
        return;
      }
      const errorMsg = err instanceof Error ? err.message : '未知错误';
      setError(`链接抓取失败：${errorMsg}`);
      setPhase('detect', 'failed');
      void _persistPhaseSnapshot(get, 'detect', 'failed', { error_message: errorMsg });
      toast.error(`链接抓取失败：${errorMsg}`);
      throw err;
    }
  },

  setTaskId: (taskId) => set({ taskId }),

  setRestorable: (taskId, updatedAt) =>
    set({
      restorableTaskId: taskId,
      restorableUpdatedAt: updatedAt ?? null,
    }),

  probeLatestRestorable: async () => {
    try {
      const latest = await loadLatestPipelineState();
      if (!latest.task_id || !latest.updated_at) return;
      const hasAnySnapshot = (latest.snapshots ?? []).length > 0;
      if (!hasAnySnapshot) return;

      // 只“探测”可恢复任务，不做实际恢复
      get().setRestorable(latest.task_id, latest.updated_at);
    } catch (err) {
      console.warn('[pipeline persistence] probe latest failed:', err);
    }
  },

  setText: (text) => set({ text }),
  
  setPhase: (phase, status) =>
    set((state) => ({
      phases: { ...state.phases, [phase]: status },
    })),

  setError: (error) => set({ error }),

  setContent: (content) => set({ content }),

  // 仅供模拟流式阶段展示：记录当前阶段与时间戳（便于 Chat Workbench 生成分阶段卡片）
  setSimulationStage: (stage: SimulationStage | null, at?: string | null) =>
    set({ simulationStage: stage, simulationStageAt: at ?? new Date().toISOString() }),

  hydrateFromLatest: async (opts) => {
    // 若当前已经有进行中的 task（非全 idle），不要覆盖
    const current = get();
    const hasManualText = current.text.trim() && current.text !== DEFAULT_TEXT;
    const hasProgress =
      current.detectData ||
      current.claims.length > 0 ||
      current.evidences.length > 0 ||
      current.report ||
      current.simulation ||
      current.content ||
      Object.values(current.phases).some((v) => v !== 'idle');
    if (!opts?.force) {
      if (hasProgress) return;
      if (hasManualText) return;
    }

    try {
      const latest = await loadLatestPipelineState(opts?.taskId);
      if (!latest.task_id || !latest.updated_at) return;

      // 后端没有任何快照时 phases 可能全 idle；这种情况不覆盖
      const hasAnySnapshot = (latest.snapshots ?? []).length > 0;
      if (!hasAnySnapshot) return;

      const next: Partial<PipelineState> = {
        taskId: latest.task_id,
        text: latest.input_text || current.text,
        phases: latest.phases,
        error: null,
        isFromHistory: false,
      };

      // meta 中可能包含 recordId（例如 chat 会话写入的 snapshot meta）
      const metaRecordId = (latest.meta as any)?.recordId ?? (latest.meta as any)?.record_id;
      if (typeof metaRecordId === 'string' && metaRecordId) {
        next.recordId = metaRecordId;
      }

      for (const snap of latest.snapshots ?? []) {
        const payload = (snap.payload ?? {}) as any;
        switch (snap.phase) {
          case 'detect':
            if (payload.detectData) next.detectData = payload.detectData as DetectResponse;
            if (payload.strategy) next.strategy = payload.strategy as StrategyConfig;
            if (payload.sourceMeta) next.sourceMeta = payload.sourceMeta;
            break;
          case 'claims':
            if (Array.isArray(payload.claims)) next.claims = payload.claims as ClaimItem[];
            break;
          case 'evidence':
            if (Array.isArray(payload.rawEvidences)) next.rawEvidences = payload.rawEvidences as EvidenceItem[];
            if (Array.isArray(payload.evidences)) next.evidences = payload.evidences as EvidenceItem[];
            break;
          case 'report':
            if (payload.report) next.report = payload.report as ReportResponse;
            if (typeof payload.recordId === 'string') next.recordId = payload.recordId as string;
            if (payload.sourceMeta) next.sourceMeta = payload.sourceMeta;
            break;
          case 'simulation':
            if (payload.simulation) next.simulation = payload.simulation as SimulateResponse;
            break;
          case 'content':
            if (payload.content) next.content = payload.content as ContentDraft;
            break;
        }
      }

      set(next as any);
      if (!opts?.silent) {
        toast.success('已从数据库恢复上一次分析进度');
      }
    } catch (err) {
      console.warn('[pipeline persistence] load-latest failed:', err);
    }
  },

  reset: () => set(initialState),

  interruptPipeline: () => {
    const c = get().abortController;
    if (c && !c.signal.aborted) {
      c.abort();
      // 立即把当前 running 的阶段标记为 canceled，保证 UI 立刻出现“可继续/可重试”入口
      const runningPhases: Phase[] = [];
      set((state) => {
        const next = { ...state.phases };
        (Object.keys(next) as Phase[]).forEach((p) => {
          if (next[p] === 'running') {
            next[p] = 'canceled';
            runningPhases.push(p);
          }
        });
        return {
          phases: next,
          abortController: null,
        };
      });

      // 中断也要落库（running -> canceled）
      for (const p of runningPhases) {
        void _persistPhaseSnapshot(get, p, 'canceled', {
          error_message: 'aborted',
        });
      }
      toast.info('已请求中断分析');
    }
  },

  runPipeline: async (opts) => {
    const { text, setPhase, setError } = get();

    // 每次启动分析都生成新的 AbortController
    const controller = new AbortController();
    const signal = controller.signal;
    
    const taskId = (opts?.taskId && String(opts.taskId)) || _makeTaskId();
    set({
      taskId,
      error: null,
      detectData: null,
      strategy: null,
      sourceMeta: opts?.taskId ? get().sourceMeta : null,
      claims: [],
      rawEvidences: [],
      evidences: [],
      report: null,
      simulation: null,
      content: null,
      phases: INIT_PHASE_STATE,
      recordId: null,
      abortController: controller,
      // 从历史记录回放后再发起新的分析时，必须重置该标记；否则会导致后续写回历史（content/simulation 等）被误拦截
      isFromHistory: false,
    });

    // 初始化时也写一次（方便刷新后至少能恢复“任务已开始”）
    void _persistPhaseSnapshot(get, 'detect', 'idle', {
      payload: { note: 'task_started' },
    });

    toast.info('开始分析...');

    const pushError = (message: string, showToast = true) => {
      setError(message);
      if (showToast) {
        toast.error(message);
      }
    };

    const isAbortError = (err: unknown) => {
      const e = err as any;
      return (
        e?.name === 'AbortError' ||
        e?.code === 'ERR_CANCELED' ||
        String(e?.message ?? '').toLowerCase().includes('canceled') ||
        String(e?.message ?? '').toLowerCase().includes('aborted')
      );
    };

    setPhase('detect', 'running');
    void _persistPhaseSnapshot(get, 'detect', 'running');
    const detectPromise = detectWithSignal(text, signal)
      .then((result) => {
        set({ detectData: result, strategy: result.strategy ?? null });
        setPhase('detect', 'done');
        void _persistPhaseSnapshot(get, 'detect', 'done');
        toast.success('风险快照完成');
        if (result.truncated) {
          toast.warning('输入文本较长，已自动截断至 8000 字符以内进行分析');
        }
      })
      .catch((err) => {
        if (isAbortError(err)) {
          setPhase('detect', 'canceled');
          void _persistPhaseSnapshot(get, 'detect', 'canceled', {
            error_message: 'aborted',
          });
          return;
        }
        setPhase('detect', 'failed');
        void _persistPhaseSnapshot(get, 'detect', 'failed', {
          error_message: err instanceof Error ? err.message : '未知错误',
        });
        pushError(`风险快照失败：${err instanceof Error ? err.message : '未知错误'}`);
      });

    const deepScanPromise = (async () => {
      // Wait for detect to complete to get strategy
      await detectPromise;
      const currentStrategy = get().strategy;

      if (currentStrategy && currentStrategy.is_news === false) {
        const reason = currentStrategy.news_reason || '文本新闻特征不足';
        toast.warning(`已停止自动检测流程：${reason}`);
        setPhase('claims', 'idle');
        setPhase('evidence', 'idle');
        setPhase('report', 'idle');
        setPhase('simulation', 'idle');
        setPhase('content', 'idle');
        void _persistPhaseSnapshot(get, 'claims', 'idle', {
          error_message: 'news_gate_blocked',
          payload: { reason, detected_text_type: currentStrategy.detected_text_type },
        });
        return;
      }
      
      try {
        setPhase('claims', 'running');
        void _persistPhaseSnapshot(get, 'claims', 'running');
        if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
        const claimsResult = await detectClaimsWithSignal(text, currentStrategy, signal);
        set({ claims: claimsResult });
        setPhase('claims', 'done');
        void _persistPhaseSnapshot(get, 'claims', 'done');
        toast.success(`主张抽取完成，共 ${claimsResult.length} 条`);

        setPhase('evidence', 'running');
        void _persistPhaseSnapshot(get, 'evidence', 'running');
        let evidenceResult: EvidenceItem[] = [];
        try {
          // Step 1: 证据检索
          if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
          const rawEvidences = await detectEvidenceWithSignal(text, claimsResult, currentStrategy, signal);
          set({ rawEvidences });
          toast.success(`证据检索完成，共 ${rawEvidences.length} 条`);
          
          // Step 2: 证据聚合与对齐
          if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
          evidenceResult = await alignEvidenceWithSignal(claimsResult, rawEvidences, currentStrategy, signal);
          set({ evidences: evidenceResult });
          setPhase('evidence', 'done');
          void _persistPhaseSnapshot(get, 'evidence', 'done');
          toast.success(`证据聚合对齐完成，共 ${evidenceResult.length} 条`);
        } catch (err) {
          if (isAbortError(err)) {
            setPhase('evidence', 'canceled');
            void _persistPhaseSnapshot(get, 'evidence', 'canceled', {
              error_message: 'aborted',
            });
          } else {
            setPhase('evidence', 'failed');
            void _persistPhaseSnapshot(get, 'evidence', 'failed', {
              error_message: err instanceof Error ? err.message : '未知错误',
            });
            pushError(`证据处理失败：${err instanceof Error ? err.message : '未知错误'}`);
          }
        }

        let reportResult: ReportResponse | null = null;
        let recordId: string | null = null;
        setPhase('report', 'running');
        void _persistPhaseSnapshot(get, 'report', 'running');
        try {
          if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
          const currentDetectData = get().detectData;
          const currentSourceMeta = get().sourceMeta;
          const reportResponse = await detectReportWithSignal(
            text,
            claimsResult,
            evidenceResult,
            currentDetectData,
            currentStrategy,
            currentSourceMeta,
            signal
          );
          recordId = reportResponse.record_id;
          reportResult = {
            risk_score: reportResponse.risk_score,
            risk_level: reportResponse.risk_level,
            risk_label: reportResponse.risk_label,
            detected_scenario: reportResponse.detected_scenario,
            evidence_domains: reportResponse.evidence_domains,
            source_url: reportResponse.source_url ?? null,
            source_title: reportResponse.source_title ?? null,
            source_publish_date: reportResponse.source_publish_date ?? null,
            summary: reportResponse.summary,
            suspicious_points: reportResponse.suspicious_points,
            claim_reports: reportResponse.claim_reports,
          };
          set({ report: reportResult, recordId });
          setPhase('report', 'done');
          void _persistPhaseSnapshot(get, 'report', 'done');
          toast.success('综合报告生成完成');
        } catch (err) {
          if (isAbortError(err)) {
            setPhase('report', 'canceled');
            void _persistPhaseSnapshot(get, 'report', 'canceled', {
              error_message: 'aborted',
            });
          } else {
            setPhase('report', 'failed');
            void _persistPhaseSnapshot(get, 'report', 'failed', {
              error_message: err instanceof Error ? err.message : '未知错误',
            });
            pushError(`综合报告失败：${err instanceof Error ? err.message : '未知错误'}`);
          }
        }

        setPhase('simulation', 'running');
        void _persistPhaseSnapshot(get, 'simulation', 'running');
        try {
          await simulateStream(
            text,
            (event: SimulationStreamEvent) => {
              console.log('[Simulation Stream] Received event:', event.stage, event.data);
              const now = Date.now();
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

              // 记录阶段（供 Chat Workbench 分阶段卡片使用）
              set({
                simulationStage: event.stage,
                simulationStageAt: new Date(now).toISOString(),
              });

              // 流式阶段中也允许增量落库（避免刷新丢阶段产物）
              void _persistPhaseSnapshot(get, 'simulation', 'running');

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
            reportResult ?? undefined,
            signal
          );
          setPhase('simulation', 'done');
          void _persistPhaseSnapshot(get, 'simulation', 'done');
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
          if (isAbortError(err)) {
            setPhase('simulation', 'canceled');
            void _persistPhaseSnapshot(get, 'simulation', 'canceled', {
              error_message: 'aborted',
            });
          } else {
            setPhase('simulation', 'failed');
            void _persistPhaseSnapshot(get, 'simulation', 'failed', {
              error_message: err instanceof Error ? err.message : '未知错误',
            });
            pushError(`舆情预演失败：${err instanceof Error ? err.message : '未知错误'}`);
          }
        }
      } catch (err) {
        if (isAbortError(err)) {
          setPhase('claims', 'canceled');
          void _persistPhaseSnapshot(get, 'claims', 'canceled', {
            error_message: 'aborted',
          });
          // 下游阶段保持 idle（未开始），但 UI 允许“继续执行”
          setPhase('evidence', 'idle');
          setPhase('report', 'idle');
          setPhase('simulation', 'idle');
        } else {
          setPhase('claims', 'failed');
          void _persistPhaseSnapshot(get, 'claims', 'failed', {
            error_message: err instanceof Error ? err.message : '未知错误',
          });
          setPhase('evidence', 'idle');
          setPhase('report', 'idle');
          setPhase('simulation', 'idle');
          pushError(`主张抽取失败：${err instanceof Error ? err.message : '未知错误'}`);
        }
      }
    })();

    await Promise.allSettled([detectPromise, deepScanPromise]);

    // 清理 controller，避免下次误用
    set({ abortController: null });
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
      sourceMeta: {
        source_url: detail.report.source_url ?? null,
        source_title: detail.report.source_title ?? null,
        source_publish_date: detail.report.source_publish_date ?? null,
      },
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
    void _persistPhaseSnapshot(get, phase, 'running');
    setError(null);

    try {
      switch (phase) {
        case 'detect':
          const detectResult = await detect(text);
          set({ detectData: detectResult, strategy: detectResult.strategy ?? null });
          setPhase('detect', 'done');
          void _persistPhaseSnapshot(get, 'detect', 'done');
          toast.success('风险快照重试成功');
          break;

        case 'claims':
          const currentStrategy = get().strategy;
          const claimsResult = await detectClaims(text, currentStrategy);
          set({ claims: claimsResult });
          setPhase('claims', 'done');
          void _persistPhaseSnapshot(get, 'claims', 'done');
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
          void _persistPhaseSnapshot(get, 'evidence', 'done');
          toast.success(`证据聚合对齐完成，共 ${alignedEvidences.length} 条`);
          break;

        case 'report':
          const reportClaims = get().claims;
          const reportEvidences = get().evidences;
          const reportDetectData = get().detectData;
          const reportStrategy = get().strategy;
          const reportSourceMeta = get().sourceMeta;
          const reportResponse = await detectReport(
            text,
            reportClaims,
            reportEvidences,
            reportDetectData,
            reportStrategy,
            reportSourceMeta,
          );
          const newRecordId = reportResponse.record_id;
          const reportResult: ReportResponse = {
            risk_score: reportResponse.risk_score,
            risk_level: reportResponse.risk_level,
            risk_label: reportResponse.risk_label,
            detected_scenario: reportResponse.detected_scenario,
            evidence_domains: reportResponse.evidence_domains,
            source_url: reportResponse.source_url ?? null,
            source_title: reportResponse.source_title ?? null,
            source_publish_date: reportResponse.source_publish_date ?? null,
            summary: reportResponse.summary,
            suspicious_points: reportResponse.suspicious_points,
            claim_reports: reportResponse.claim_reports,
          };
          set({ report: reportResult, recordId: newRecordId });
          setPhase('report', 'done');
          void _persistPhaseSnapshot(get, 'report', 'done');
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
              const now = Date.now();
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
              set({
                simulationStage: event.stage,
                simulationStageAt: new Date(now).toISOString(),
              });
              void _persistPhaseSnapshot(get, 'simulation', 'running');

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
          void _persistPhaseSnapshot(get, 'simulation', 'done');
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
      void _persistPhaseSnapshot(get, phase, 'failed', {
        error_message: err instanceof Error ? err.message : '未知错误',
      });
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
