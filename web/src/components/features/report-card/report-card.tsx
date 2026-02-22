'use client';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { Skeleton } from '@/components/ui/skeleton';
import { FileText } from 'lucide-react';
import { zhRiskLabel, zhRiskLevel, zhScenario, zhDomain, zhStance, zhText, zhClaimId } from '@/lib/i18n';
import type { ReportResponse } from '@/types';

interface ReportCardProps {
  report: ReportResponse | null;
  isLoading: boolean;
}

const riskLevelColors: Record<string, string> = {
  low: 'bg-green-500',
  medium: 'bg-yellow-500',
  high: 'bg-orange-500',
  critical: 'bg-red-500',
};

function ReportCardSkeleton() {
  return (
    <Card>
      <CardHeader className="pb-2">
        <Skeleton className="h-5 w-20" />
        <Skeleton className="h-4 w-40 mt-1" />
      </CardHeader>
      <CardContent className="space-y-5">
        {/* 风险标签行 */}
        <div className="flex items-center gap-3">
          <Skeleton className="h-6 w-20 rounded-full" />
          <Skeleton className="h-6 w-16 rounded-full" />
          <Skeleton className="h-8 w-10" />
        </div>
        {/* 元信息行 */}
        <div className="grid grid-cols-2 gap-4">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-full" />
        </div>
        {/* 摘要段落 */}
        <div className="space-y-2">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-5/6" />
          <Skeleton className="h-4 w-4/5" />
        </div>
        {/* 主张结论占位 */}
        <Skeleton className="h-24 w-full rounded-lg" />
        <Skeleton className="h-24 w-full rounded-lg" />
      </CardContent>
    </Card>
  );
}

function ReportCardEmpty() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>综合报告</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex flex-col items-center gap-2 py-8 text-muted-foreground">
          <FileText className="h-8 w-8 opacity-30" />
          <p className="text-sm">报告尚未生成</p>
          <p className="text-xs opacity-60">请等待证据检索与分析完成</p>
        </div>
      </CardContent>
    </Card>
  );
}

export function ReportCard({ report, isLoading }: ReportCardProps) {
  if (isLoading) {
    return <ReportCardSkeleton />;
  }

  if (!report) {
    return <ReportCardEmpty />;
  }

  return (
    <Card className="transition-opacity duration-500 animate-in fade-in">
      <CardHeader>
        <CardTitle>综合报告</CardTitle>
        <CardDescription>完整的风险分析与建议</CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-2">
            <Badge className={riskLevelColors[report.risk_level] ?? 'bg-gray-500'}>
              {zhRiskLabel(report.risk_label)}
            </Badge>
            <Badge variant="outline">
              {zhRiskLevel(report.risk_level)}风险
            </Badge>
          </div>
          <span className="text-2xl font-bold">{report.risk_score}</span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
          <div>
            <span className="text-muted-foreground">识别场景：</span>
            <span className="ml-2">{zhScenario(report.detected_scenario)}</span>
          </div>
          <div>
            <span className="text-muted-foreground">证据覆盖域：</span>
            <span className="ml-2">
              {report.evidence_domains.map((d) => zhDomain(d)).join('、') || '暂无'}
            </span>
          </div>
        </div>

        <p className="text-sm">{zhText(report.summary)}</p>

        {report.suspicious_points.length > 0 && (
          <div>
            <h4 className="font-medium mb-2">可疑点</h4>
            <ul className="space-y-1 text-sm">
              {report.suspicious_points.map((point, index) => (
                <li key={index} className="flex items-start gap-2">
                  <span className="text-muted-foreground">•</span>
                  {zhText(point)}
                </li>
              ))}
            </ul>
          </div>
        )}

        <Separator />

        <div>
          <h4 className="font-medium mb-3">主张级结论</h4>
          <div className="space-y-4">
            {report.claim_reports.map((item) => (
              <div
                key={item.claim.claim_id}
                className="border rounded-lg p-3 hover:bg-muted/20 transition-colors"
              >
                <div className="flex items-start gap-2 mb-2">
                  <Badge variant="outline">{zhClaimId(item.claim.claim_id)}</Badge>
                  <Badge
                    className={
                      item.final_stance === 'support'
                        ? 'bg-green-100 text-green-800'
                        : item.final_stance === 'refute'
                        ? 'bg-red-100 text-red-800'
                        : 'bg-gray-100 text-gray-800'
                    }
                  >
                    {zhStance(item.final_stance)}
                  </Badge>
                </div>
                <p className="text-sm mb-2">{item.claim.claim_text}</p>
                {item.notes.length > 0 && (
                  <div className="text-xs text-muted-foreground space-y-1">
                    {item.notes.map((note, idx) => (
                      <p key={idx}>{zhText(note)}</p>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
