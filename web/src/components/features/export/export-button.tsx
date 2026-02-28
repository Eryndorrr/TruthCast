'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Download, FileJson, FileText, FileType2, FileType, Loader2 } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { downloadJson, downloadMarkdown, type ExportData } from '@/lib/export';
import { downloadPdfExport, downloadWordExport } from '@/services/api';

interface ExportButtonProps {
  data: ExportData;
}

export function ExportButton({ data }: ExportButtonProps) {
  const [open, setOpen] = useState(false);
  const [exporting, setExporting] = useState<string | null>(null);

  const handleExport = async (format: 'json' | 'md' | 'pdf' | 'word') => {
    setExporting(format);
    try {
      const timestamp = new Date().toISOString().slice(0, 10);
      const filename = `truthcast-report-${timestamp}`;
      
      if (format === 'json') {
        downloadJson(data, `${filename}.json`);
      } else if (format === 'md') {
        downloadMarkdown(data, `${filename}.md`);
      } else if (format === 'pdf') {
        await downloadPdfExport(data);
      } else {
        await downloadWordExport(data);
      }
      
      setOpen(false);
    } finally {
      setExporting(null);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          <Download className="h-4 w-4 mr-2" />
          导出报告
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>导出报告</DialogTitle>
          <DialogDescription>选择导出格式</DialogDescription>
        </DialogHeader>
        <div className="grid gap-3 py-4">
          <Button
            variant="outline"
            className="justify-start"
            onClick={() => handleExport('json')}
            disabled={exporting !== null}
          >
            {exporting === 'json' ? (
              <Loader2 className="h-4 w-4 mr-3 animate-spin" />
            ) : (
              <FileJson className="h-4 w-4 mr-3" />
            )}
            JSON 格式
            <span className="ml-auto text-muted-foreground text-xs">完整数据</span>
          </Button>
          <Button
            variant="outline"
            className="justify-start"
            onClick={() => handleExport('md')}
            disabled={exporting !== null}
          >
            {exporting === 'md' ? (
              <Loader2 className="h-4 w-4 mr-3 animate-spin" />
            ) : (
              <FileText className="h-4 w-4 mr-3" />
            )}
            Markdown 格式
            <span className="ml-auto text-muted-foreground text-xs">可读性高</span>
          </Button>
          <Button
            variant="outline"
            className="justify-start"
            onClick={() => handleExport('pdf')}
            disabled={exporting !== null}
          >
            {exporting === 'pdf' ? (
              <Loader2 className="h-4 w-4 mr-3 animate-spin" />
            ) : (
              <FileType2 className="h-4 w-4 mr-3" />
            )}
            PDF 格式
            <span className="ml-auto text-muted-foreground text-xs">后端生成</span>
          </Button>
          <Button
            variant="outline"
            className="justify-start"
            onClick={() => handleExport('word')}
            disabled={exporting !== null}
          >
            {exporting === 'word' ? (
              <Loader2 className="h-4 w-4 mr-3 animate-spin" />
            ) : (
              <FileType className="h-4 w-4 mr-3" />
            )}
            Word 格式
            <span className="ml-auto text-muted-foreground text-xs">后端生成</span>
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
