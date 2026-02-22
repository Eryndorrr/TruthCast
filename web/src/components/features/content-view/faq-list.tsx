'use client';

import { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { FAQItem } from '@/types';

interface FAQListProps {
  faq: FAQItem[];
}

const CATEGORY_LABELS: Record<string, string> = {
  core: '核心问题',
  detail: '细节问题',
  background: '背景问题',
  general: '一般问题',
};

const CATEGORY_COLORS: Record<string, 'default' | 'secondary' | 'outline'> = {
  core: 'default',
  detail: 'secondary',
  background: 'outline',
  general: 'outline',
};

export function FAQList({ faq }: FAQListProps) {
  const [expandedIndex, setExpandedIndex] = useState<number | null>(0);

  if (!faq || faq.length === 0) {
    return null;
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-lg">常见问题解答 (FAQ)</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {faq.map((item, index) => (
          <div
            key={index}
            className="rounded-lg border bg-card p-3 cursor-pointer hover:bg-accent/50 transition-colors"
            onClick={() => setExpandedIndex(expandedIndex === index ? null : index)}
          >
            <div className="flex items-start justify-between gap-2">
              <div className="flex items-start gap-2">
                <span className="font-medium text-sm text-primary">Q{index + 1}:</span>
                <span className="font-medium text-sm">{item.question}</span>
              </div>
              <Badge variant={CATEGORY_COLORS[item.category] || 'outline'} className="shrink-0">
                {CATEGORY_LABELS[item.category] || item.category}
              </Badge>
            </div>
            {expandedIndex === index && (
              <div className="mt-2 pt-2 border-t">
                <div className="flex items-start gap-2">
                  <span className="font-medium text-sm text-muted-foreground">A:</span>
                  <span className="text-sm text-muted-foreground leading-relaxed">
                    {item.answer}
                  </span>
                </div>
              </div>
            )}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
