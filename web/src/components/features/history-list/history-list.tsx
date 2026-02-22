'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Separator } from '@/components/ui/separator';
import { History, Eye, MessageSquare, RefreshCw, ExternalLink } from 'lucide-react';
import { zhRiskLabel, zhScenario, zhDomain } from '@/lib/i18n';
import { useHistoryList, useHistoryDetail, useSubmitFeedback } from '@/hooks/use-history';
import { ExportButton } from '@/components/features/export';
import { usePipelineStore } from '@/stores/pipeline-store';

const riskLabelColors: Record<string, string> = {
  credible: 'bg-green-500',
  suspicious: 'bg-yellow-500',
  high_risk: 'bg-orange-500',
  needs_context: 'bg-blue-500',
  likely_misinformation: 'bg-red-500',
};

export function HistoryList() {
  const router = useRouter();
  const { items, isLoading, error, refresh } = useHistoryList();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const { detail, isLoading: detailLoading } = useHistoryDetail(selectedId);
  const submitFeedback = useSubmitFeedback();
  const loadFromHistory = usePipelineStore((state) => state.loadFromHistory);

  const [feedbackStatus, setFeedbackStatus] = useState<'accurate' | 'inaccurate' | 'evidence_irrelevant'>('accurate');
  const [feedbackNote, setFeedbackNote] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handleViewAnalysis = () => {
    if (!detail) return;
    loadFromHistory(detail, detail.simulation);
    toast.success('已加载历史记录');
    router.push('/result');
  };

  const handleViewSimulation = () => {
    if (!detail) return;
    loadFromHistory(detail, detail.simulation);
    toast.success('已加载历史记录');
    router.push('/simulation');
  };

  const handleSubmitFeedback = async () => {
    if (!selectedId) return;
    setSubmitting(true);
    try {
      await submitFeedback(selectedId, feedbackStatus, feedbackNote);
      toast.success('反馈提交成功');
      refresh();
      setSelectedId(null);
      setFeedbackNote('');
    } catch (err) {
      console.error('Feedback submission failed:', err);
      toast.error('反馈提交失败');
    } finally {
      setSubmitting(false);
    }
  };

  if (error) {
    return (
      <Card>
        <CardContent className="py-8">
          <p className="text-destructive text-center">加载失败: {error.message}</p>
          <div className="flex justify-center mt-4">
            <Button onClick={() => refresh()} variant="outline">
              <RefreshCw className="h-4 w-4 mr-2" />
              重试
            </Button>
          </div>
        </CardContent>
      </Card>
    );
  }

  if (isLoading) {
    return (
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <Skeleton className="h-6 w-24" />
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {[1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-20 w-full" />
              ))}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <Skeleton className="h-6 w-24" />
          </CardHeader>
          <CardContent>
            <Skeleton className="h-64 w-full" />
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 xl:grid-cols-2 gap-4 md:gap-6">
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <History className="h-5 w-5" />
              <CardTitle>历史记录</CardTitle>
            </div>
            <Button onClick={() => refresh()} variant="ghost" size="sm">
              <RefreshCw className="h-4 w-4" />
            </Button>
          </div>
          <CardDescription>共 {items.length} 条记录</CardDescription>
        </CardHeader>
        <CardContent className="max-h-[60vh] overflow-y-auto">
          {items.length === 0 ? (
            <div className="flex flex-col items-center gap-2 py-10 text-muted-foreground">
              <History className="h-8 w-8 opacity-25" />
              <p className="text-sm font-medium">暂无历史记录</p>
              <p className="text-xs opacity-60">完成一次分析后，结果将自动保存在此</p>
            </div>
          ) : (
            <div className="space-y-3">
              {items.map((item) => (
                <div
                  key={item.id}
                  className={`border rounded-lg p-3 cursor-pointer transition-colors ${
                    selectedId === item.id ? 'border-primary bg-primary/5' : 'hover:bg-muted/50'
                  }`}
                  onClick={() => setSelectedId(item.id)}
                >
                  <div className="flex items-start justify-between gap-2 mb-2">
                    <p className="text-sm line-clamp-2 flex-1">{item.input_preview}</p>
                    <Button variant="ghost" size="icon" className="shrink-0 h-8 w-8">
                      <Eye className="h-4 w-4" />
                    </Button>
                  </div>
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    <Badge className={riskLabelColors[item.risk_label] ?? 'bg-gray-500'}>
                      {zhRiskLabel(item.risk_label)}
                    </Badge>
                    <span className="text-muted-foreground">分数: {item.risk_score}</span>
                    <span className="text-muted-foreground hidden sm:inline">
                      {new Date(item.created_at).toLocaleString('zh-CN')}
                    </span>
                  </div>
                  {item.feedback_status && (
                    <div className="mt-2">
                      <Badge variant="outline" className="text-xs">
                        <MessageSquare className="h-3 w-3 mr-1" />
                        已反馈: {item.feedback_status}
                      </Badge>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle>记录详情</CardTitle>
            {detail && (
              <ExportButton
                data={{
                  inputText: detail.input_text,
                  detectData: null,
                  claims: [],
                  evidences: [],
                  report: detail.report,
                  simulation: null,
                  exportedAt: new Date(detail.created_at).toLocaleString('zh-CN'),
                }}
              />
            )}
          </div>
        </CardHeader>
        <CardContent>
          {detailLoading ? (
            <div className="space-y-4">
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-32 w-full" />
              <Skeleton className="h-32 w-full" />
            </div>
          ) : detail ? (
            <div className="space-y-4">
              <div className="flex gap-2">
                <Button onClick={handleViewAnalysis} className="flex-1">
                  <ExternalLink className="h-4 w-4 mr-2" />
                  查看分析结果
                </Button>
                <Button onClick={handleViewSimulation} variant="outline" className="flex-1">
                  <ExternalLink className="h-4 w-4 mr-2" />
                  查看舆情预演
                </Button>
              </div>

              <Separator />

              <div>
                <h4 className="text-sm font-medium mb-2">原始输入</h4>
                <p className="text-sm bg-muted p-3 rounded-lg">{detail.input_text}</p>
              </div>

              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <span className="text-muted-foreground">风险标签：</span>
                  <Badge className={riskLabelColors[detail.risk_label] ?? 'bg-gray-500'}>
                    {zhRiskLabel(detail.risk_label)}
                  </Badge>
                </div>
                <div>
                  <span className="text-muted-foreground">风险分数：</span>
                  <span className="font-medium">{detail.risk_score}</span>
                </div>
                <div>
                  <span className="text-muted-foreground">识别场景：</span>
                  <span>{zhScenario(detail.detected_scenario)}</span>
                </div>
                <div>
                  <span className="text-muted-foreground">证据域：</span>
                  <span>{detail.evidence_domains.map((d) => zhDomain(d)).join('、') || '暂无'}</span>
                </div>
              </div>

              <Separator />

              <div>
                <h4 className="text-sm font-medium mb-2">提交反馈</h4>
                <div className="space-y-3">
                  <div className="flex gap-2">
                    {(['accurate', 'inaccurate', 'evidence_irrelevant'] as const).map((status) => (
                      <Button
                        key={status}
                        size="sm"
                        variant={feedbackStatus === status ? 'default' : 'outline'}
                        onClick={() => setFeedbackStatus(status)}
                      >
                        {status === 'accurate' ? '准确' : status === 'inaccurate' ? '不准确' : '证据无关'}
                      </Button>
                    ))}
                  </div>
                  <Textarea
                    placeholder="添加备注（可选）"
                    value={feedbackNote}
                    onChange={(e) => setFeedbackNote(e.target.value)}
                    rows={2}
                  />
                  <Button onClick={handleSubmitFeedback} disabled={submitting}>
                    {submitting ? '提交中...' : '提交反馈'}
                  </Button>
                </div>
              </div>

              {detail.feedback_status && (
                <div className="text-sm text-muted-foreground">
                  已收到反馈: {detail.feedback_status}
                  {detail.feedback_note && ` - ${detail.feedback_note}`}
                </div>
              )}
            </div>
          ) : (
            <p className="text-muted-foreground text-center py-8">选择一条记录查看详情</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
