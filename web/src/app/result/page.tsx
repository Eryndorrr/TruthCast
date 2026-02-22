'use client';

import { ProgressTimeline } from '@/components/layout';
import { RiskOverview, ClaimList, EvidenceChain, ReportCard, ExportButton } from '@/components/features';
import { ErrorBoundary } from '@/components/ui/error-boundary';
import { usePipelineStore } from '@/stores/pipeline-store';
import type { Phase } from '@/types';
import { CheckCircle2 } from 'lucide-react';

export default function ResultPage() {
  const { text, detectData, claims, rawEvidences, evidences, report, simulation, content, phases, retryPhase } = usePipelineStore();

  const hasReport = report !== null;
  const allDone =
    phases.detect === 'done' &&
    phases.claims === 'done' &&
    phases.evidence === 'done' &&
    phases.report === 'done';

  const handleRetry = (phase: Phase) => {
    retryPhase(phase);
  };

  return (
    <div className="space-y-6 px-2 md:px-0">
      {/* 进度时间线 + 导出按钮 */}
      <div className="flex flex-col items-center gap-4">
        <ProgressTimeline
          phases={phases}
          onRetry={handleRetry}
          showRetry={true}
        />
        {hasReport && (
          <ExportButton
            data={{
              inputText: text,
              detectData,
              claims,
              evidences,
              report,
              simulation,
              content: content ?? null,
              exportedAt: new Date().toLocaleString('zh-CN'),
            }}
          />
        )}
      </div>

      {/* 分析完成庆祝 banner */}
      {allDone && (
        <div className="flex items-center gap-3 px-4 py-3 rounded-lg bg-green-50 border border-green-200 text-green-800 text-sm animate-in fade-in duration-700">
          <CheckCircle2 className="h-5 w-5 shrink-0 text-green-600" />
          <span className="font-medium">分析完成！</span>
          <span className="text-green-700">全链路核查已结束，请查看下方各模块结果。</span>
        </div>
      )}

      {/* 风险概览 + 主张抽取 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 md:gap-6">
        <ErrorBoundary title="风险概览加载失败">
          <RiskOverview data={detectData} isLoading={phases.detect === 'running'} />
        </ErrorBoundary>
        <ErrorBoundary title="主张抽取加载失败">
          <ClaimList claims={claims} isLoading={phases.claims === 'running'} />
        </ErrorBoundary>
      </div>

      {/* 证据链 */}
      <ErrorBoundary title="证据链加载失败">
        <EvidenceChain
          rawEvidences={rawEvidences}
          evidences={evidences}
          claims={claims}
          report={report}
          isLoading={phases.evidence === 'running'}
        />
      </ErrorBoundary>

      {/* 综合报告 */}
      <ErrorBoundary title="综合报告加载失败">
        <ReportCard report={report} isLoading={phases.report === 'running'} />
      </ErrorBoundary>
    </div>
  );
}
