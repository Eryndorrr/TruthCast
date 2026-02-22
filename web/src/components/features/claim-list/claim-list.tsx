'use client';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { ClipboardList } from 'lucide-react';
import { zhClaimId } from '@/lib/i18n';
import type { ClaimItem } from '@/types';

interface ClaimListProps {
  claims: ClaimItem[];
  isLoading: boolean;
}

function ClaimListSkeleton() {
  return (
    <Card>
      <CardHeader className="pb-2">
        <Skeleton className="h-5 w-20" />
        <Skeleton className="h-4 w-36 mt-1" />
      </CardHeader>
      <CardContent>
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="border rounded-lg p-3 space-y-2">
              <div className="flex items-start gap-2">
                <Skeleton className="h-5 w-12 rounded-full shrink-0" />
                <Skeleton className="h-4 w-full" />
              </div>
              <div className="flex gap-3">
                <Skeleton className="h-3 w-20" />
                <Skeleton className="h-3 w-16" />
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function ClaimListEmpty() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>主张抽取</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex flex-col items-center gap-2 py-6 text-muted-foreground">
          <ClipboardList className="h-8 w-8 opacity-30" />
          <p className="text-sm">暂未抽取到可核查主张</p>
          <p className="text-xs opacity-60">文本可能较短，或内容尚在分析中</p>
        </div>
      </CardContent>
    </Card>
  );
}

export function ClaimList({ claims, isLoading }: ClaimListProps) {
  if (isLoading) {
    return <ClaimListSkeleton />;
  }

  if (claims.length === 0) {
    return <ClaimListEmpty />;
  }

  return (
    <Card className="transition-opacity duration-500 animate-in fade-in">
      <CardHeader>
        <CardTitle>主张抽取</CardTitle>
        <CardDescription>从文本中提取的可核查主张</CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="space-y-3">
          {claims.map((claim) => (
            <li key={claim.claim_id} className="border rounded-lg p-3 hover:bg-muted/30 transition-colors">
              <div className="flex items-start gap-2">
                <Badge variant="outline" className="shrink-0">
                  {zhClaimId(claim.claim_id)}
                </Badge>
                <p className="text-sm">{claim.claim_text}</p>
              </div>
              {(claim.entity || claim.time || claim.location || claim.value) && (
                <div className="mt-2 flex flex-wrap gap-2 text-xs text-muted-foreground">
                  {claim.entity && <span>实体: {claim.entity}</span>}
                  {claim.time && <span>时间: {claim.time}</span>}
                  {claim.location && <span>地点: {claim.location}</span>}
                  {claim.value && <span>数值: {claim.value}</span>}
                </div>
              )}
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
