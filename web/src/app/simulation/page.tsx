'use client';

import { ProgressTimeline } from '@/components/layout';
import { SimulationView, ExportButton } from '@/components/features';
import { ErrorBoundary } from '@/components/ui/error-boundary';
import { usePipelineStore } from '@/stores/pipeline-store';
import type { Phase } from '@/types';

export default function SimulationPage() {
  const { text, detectData, claims, evidences, report, simulation, content, phases, retryPhase } = usePipelineStore();

  const hasReport = report !== null;

  const handleRetry = (phase: Phase) => {
    retryPhase(phase);
  };

  return (
    <div className="space-y-6">
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
      <ErrorBoundary title="舆情预演加载失败">
        <SimulationView simulation={simulation} isLoading={phases.simulation === 'running'} />
      </ErrorBoundary>
    </div>
  );
}
