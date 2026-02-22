'use client';

import { useState } from 'react';
import type { ReactNode } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { ClarificationContent, ClarificationStyle } from '@/types';

interface ClarificationCardProps {
  clarification: ClarificationContent;
  style?: ClarificationStyle;
  title?: string;
  meta?: string;
  extraActions?: ReactNode;
  onCopy?: (text: string) => void;
}

const STYLE_LABELS: Record<ClarificationStyle, string> = {
  formal: '正式严肃',
  friendly: '亲切友好',
  neutral: '中性客观',
};

const LENGTH_LABELS = {
  short: { label: '短版', desc: '约100字' },
  medium: { label: '中版', desc: '约300字' },
  long: { label: '长版', desc: '约600字' },
};

export function ClarificationCard({ 
  clarification, 
  style = 'neutral',
  title = '澄清稿',
  meta,
  extraActions,
  onCopy 
}: ClarificationCardProps) {
  const [activeTab, setActiveTab] = useState<'short' | 'medium' | 'long'>('medium');
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    const text = clarification[activeTab];
    navigator.clipboard.writeText(text);
    setCopied(true);
    onCopy?.(text);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-lg">{title}</CardTitle>
          <div className="flex items-center gap-2">
            <Badge variant="outline">{STYLE_LABELS[style]}</Badge>
            {meta && (
              <span className="text-xs text-muted-foreground">{meta}</span>
            )}
            {extraActions}
            <Button 
              variant="outline" 
              size="sm" 
              onClick={handleCopy}
            >
              {copied ? '已复制 ✓' : '复制'}
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as typeof activeTab)}>
          <TabsList className="grid w-full grid-cols-3">
            <TabsTrigger value="short">
              短版 <span className="ml-1 text-xs text-muted-foreground">(~100字)</span>
            </TabsTrigger>
            <TabsTrigger value="medium">
              中版 <span className="ml-1 text-xs text-muted-foreground">(~300字)</span>
            </TabsTrigger>
            <TabsTrigger value="long">
              长版 <span className="ml-1 text-xs text-muted-foreground">(~600字)</span>
            </TabsTrigger>
          </TabsList>
          <TabsContent value="short" className="mt-4">
            <div className="rounded-md bg-muted/50 p-4 text-sm leading-relaxed">
              {clarification.short}
            </div>
          </TabsContent>
          <TabsContent value="medium" className="mt-4">
            <div className="rounded-md bg-muted/50 p-4 text-sm leading-relaxed">
              {clarification.medium}
            </div>
          </TabsContent>
          <TabsContent value="long" className="mt-4">
            <div className="rounded-md bg-muted/50 p-4 text-sm leading-relaxed whitespace-pre-wrap">
              {clarification.long}
            </div>
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}
