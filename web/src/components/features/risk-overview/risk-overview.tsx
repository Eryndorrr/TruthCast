'use client';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { ShieldAlert } from 'lucide-react';
import { zhRiskLabel, zhText } from '@/lib/i18n';
import type { DetectResponse } from '@/types';

interface RiskOverviewProps {
  data: DetectResponse | null;
  isLoading: boolean;
}

// 精细化骨架屏
function RiskOverviewSkeleton() {
  return (
    <Card>
      <CardHeader className="pb-2">
        <Skeleton className="h-5 w-20" />
        <Skeleton className="h-4 w-32 mt-1" />
      </CardHeader>
      <CardContent className="space-y-4">
        {/* 标签行 */}
        <div className="flex items-center gap-3">
          <Skeleton className="h-6 w-20 rounded-full" />
          <Skeleton className="h-4 w-14" />
          <Skeleton className="h-4 w-16" />
        </div>
        {/* 理由列表 */}
        <div className="space-y-2">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-5/6" />
          <Skeleton className="h-4 w-4/6" />
        </div>
      </CardContent>
    </Card>
  );
}

// 空状态
function RiskOverviewEmpty() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>风险概览</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex flex-col items-center gap-2 py-6 text-muted-foreground">
          <ShieldAlert className="h-8 w-8 opacity-30" />
          <p className="text-sm">等待风险快照结果…</p>
          <p className="text-xs opacity-60">提交文本后系统将自动评估</p>
        </div>
      </CardContent>
    </Card>
  );
}

export function RiskOverview({ data, isLoading }: RiskOverviewProps) {
  if (isLoading) {
    return <RiskOverviewSkeleton />;
  }

  if (!data) {
    return <RiskOverviewEmpty />;
  }

  const labelColors: Record<string, string> = {
    credible: 'bg-green-500',
    suspicious: 'bg-yellow-500',
    high_risk: 'bg-orange-500',
    needs_context: 'bg-blue-500',
    likely_misinformation: 'bg-red-500',
  };

  const scoreBarColor: Record<string, string> = {
    credible: 'bg-green-400',
    suspicious: 'bg-yellow-400',
    high_risk: 'bg-orange-400',
    needs_context: 'bg-blue-400',
    likely_misinformation: 'bg-red-400',
  };

  return (
    <Card className="transition-opacity duration-500 animate-in fade-in">
      <CardHeader>
        <CardTitle>风险概览</CardTitle>
        <CardDescription>快速风险快照评估</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center gap-3">
          <Badge className={labelColors[data.label] ?? 'bg-gray-500'}>
            {zhRiskLabel(data.label)}
          </Badge>
          <span className="text-sm text-muted-foreground">
            风险分数: <span className="font-semibold text-foreground">{data.score}</span>
          </span>
          <span className="text-sm text-muted-foreground">
            置信度: <span className="font-semibold text-foreground">{(data.confidence * 100).toFixed(0)}%</span>
          </span>
        </div>

        {/* 风险评分进度条 */}
        <div className="space-y-1">
          <div className="flex justify-between text-xs text-muted-foreground">
            <span>安全</span>
            <span>高危</span>
          </div>
          <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-700 ${scoreBarColor[data.label] ?? 'bg-gray-400'}`}
              style={{ width: `${Math.min(100, Math.max(0, data.score))}%` }}
            />
          </div>
        </div>

        <ul className="space-y-1.5 text-sm">
          {data.reasons.map((reason, index) => (
            <li key={index} className="flex items-start gap-2">
              <span className="text-muted-foreground mt-0.5">•</span>
              <span>{zhText(reason)}</span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
