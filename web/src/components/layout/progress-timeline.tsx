'use client';

import { cn } from '@/lib/utils';
import { CheckCircle2, Circle, Loader2, XCircle, RotateCcw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import type { Phase, PhaseStatus } from '@/types';

interface PhaseState {
  detect: PhaseStatus;
  claims: PhaseStatus;
  evidence: PhaseStatus;
  report: PhaseStatus;
  simulation: PhaseStatus;
  content: PhaseStatus;
}

const phaseLabels: Record<Phase, string> = {
  detect: '风险快照',
  claims: '主张抽取',
  evidence: '证据检索',
  report: '综合报告',
  simulation: '舆情预演',
  content: '应对内容',
};

const phaseShortLabels: Record<Phase, string> = {
  detect: '快照',
  claims: '主张',
  evidence: '证据',
  report: '报告',
  simulation: '预演',
  content: '应对',
};

const phaseOrder: Phase[] = ['detect', 'claims', 'evidence', 'report', 'simulation', 'content'];

interface ProgressTimelineProps {
  phases: PhaseState;
  onRetry?: (phase: Phase) => void;
  showRetry?: boolean;
}

export function ProgressTimeline({ phases, onRetry, showRetry = true }: ProgressTimelineProps) {
  return (
    <>
      {/* Desktop: Horizontal */}
      <div className="hidden md:flex items-center justify-center gap-2 py-4">
        {phaseOrder.map((phase, index) => (
          <div key={phase} className="flex items-center">
            <PhaseIndicator 
              phase={phase} 
              status={phases[phase]} 
              onRetry={onRetry}
              showRetry={showRetry}
              compact={false}
            />
            {index < phaseOrder.length - 1 && (
              <div
                className={cn(
                  'mx-2 h-0.5 w-8',
                  phases[phase] === 'done' ? 'bg-green-500' : 'bg-muted'
                )}
              />
            )}
          </div>
        ))}
      </div>
      
      {/* Mobile: Vertical */}
      <div className="md:hidden flex flex-col items-start gap-2 py-3 px-2">
        {phaseOrder.map((phase, index) => (
          <div key={phase} className="flex items-start w-full">
            <div className="flex flex-col items-center mr-3">
              <PhaseIndicator 
                phase={phase} 
                status={phases[phase]} 
                onRetry={onRetry}
                showRetry={showRetry}
                compact={true}
              />
              {index < phaseOrder.length - 1 && (
                <div
                  className={cn(
                    'w-0.5 h-4 mt-1',
                    phases[phase] === 'done' ? 'bg-green-500' : 'bg-muted'
                  )}
                />
              )}
            </div>
          </div>
        ))}
      </div>
    </>
  );
}

function PhaseIndicator({ 
  phase, 
  status,
  onRetry,
  showRetry,
  compact,
}: { 
  phase: Phase; 
  status: PhaseStatus;
  onRetry?: (phase: Phase) => void;
  showRetry?: boolean;
  compact: boolean;
}) {
  const icons = {
    idle: <Circle className={cn(compact ? "h-4 w-4" : "h-5 w-5", "text-muted-foreground")} />,
    running: <Loader2 className={cn(compact ? "h-4 w-4" : "h-5 w-5", "text-blue-500 animate-spin")} />,
    done: <CheckCircle2 className={cn(compact ? "h-4 w-4" : "h-5 w-5", "text-green-500")} />,
    failed: <XCircle className={cn(compact ? "h-4 w-4" : "h-5 w-5", "text-red-500")} />,
  };

  const handleRetry = () => {
    if (onRetry) {
      onRetry(phase);
    }
  };

  const label = compact ? phaseShortLabels[phase] : phaseLabels[phase];
  const canRetry = status === 'done' || status === 'failed';

  return (
    <div
      className={cn(
        'flex items-center gap-1.5 rounded-full',
        compact ? 'px-2 py-1 text-xs' : 'px-3 py-1.5 text-sm',
        status === 'running' && 'bg-blue-50 dark:bg-blue-950',
        status === 'done' && 'bg-green-50 dark:bg-green-950',
        status === 'failed' && 'bg-red-50 dark:bg-red-950'
      )}
    >
      {icons[status]}
      <span className="font-medium">{label}</span>
      {canRetry && showRetry && onRetry && (
        <Button
          variant="ghost"
          size="icon"
          className={cn(
            "text-muted-foreground hover:text-foreground",
            compact ? "h-4 w-4 ml-0.5" : "h-5 w-5 ml-1"
          )}
          onClick={handleRetry}
          title={status === 'failed' ? '重试' : '重新执行'}
        >
          <RotateCcw className={compact ? "h-2.5 w-2.5" : "h-3 w-3"} />
        </Button>
      )}
    </div>
  );
}
