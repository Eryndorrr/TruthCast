import type {
  ClaimItem,
  ContentDraft,
  ClarificationVariant,
  EvidenceItem,
  ReportResponse,
  SimulateResponse,
  DetectResponse,
} from '@/types';
import { zhRiskLabel, zhRiskLevel, zhScenario, zhDomain, zhStance, zhSourceType, zhText } from './i18n';

export interface ExportData {
  inputText: string;
  detectData: DetectResponse | null;
  claims: ClaimItem[];
  evidences: EvidenceItem[];
  report: ReportResponse | null;
  simulation: SimulateResponse | null;
  content?: ContentDraft | null;
  exportedAt: string;
}

function resolvePrimaryClarification(content?: ContentDraft | null): ClarificationVariant | null {
  if (!content) return null;
  const list = content.clarifications ?? [];
  if (content.primary_clarification_id) {
    return list.find((v) => v.id === content.primary_clarification_id) ?? null;
  }
  // fallback: latest
  return (
    [...list].sort((a, b) => (b.generated_at || '').localeCompare(a.generated_at || ''))[0] ?? null
  );
}

export function downloadJson(data: ExportData, filename = 'truthcast-report.json'): void {
  const json = JSON.stringify(data, null, 2);
  const blob = new Blob([json], { type: 'application/json;charset=utf-8' });
  downloadBlob(blob, filename);
}

export function downloadMarkdown(data: ExportData, filename = 'truthcast-report.md'): void {
  const md = generateMarkdown(data);
  const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' });
  downloadBlob(blob, filename);
}

function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function generateMarkdown(data: ExportData): string {
  const lines: string[] = [];

  lines.push('# TruthCast 智能研判报告');
  lines.push('');
  lines.push(`**导出时间**: ${data.exportedAt}`);
  lines.push('');

  // 输入文本
  lines.push('## 原始输入');
  lines.push('');
  lines.push('> ' + data.inputText.replace(/\n/g, '\n> '));
  lines.push('');

  // 风险快照
  if (data.detectData) {
    lines.push('## 风险快照');
    lines.push('');
    lines.push(`| 项目 | 值 |`);
    lines.push(`|------|-----|`);
    lines.push(`| 风险标签 | ${zhRiskLabel(data.detectData.label)} |`);
    lines.push(`| 风险分数 | ${data.detectData.score} |`);
    lines.push(`| 置信度 | ${data.detectData.confidence} |`);
    lines.push('');
    lines.push('**风险理由**:');
    lines.push('');
    data.detectData.reasons.forEach((r) => {
      lines.push(`- ${zhText(r)}`);
    });
    lines.push('');
  }

  // 主张抽取
  if (data.claims.length > 0) {
    lines.push('## 主张抽取');
    lines.push('');
    lines.push('| ID | 主张内容 |');
    lines.push('|----|----------|');
    data.claims.forEach((c) => {
      lines.push(`| ${c.claim_id} | ${c.claim_text} |`);
    });
    lines.push('');
  }

  // 证据链（优先使用 report 中经过摘要和对齐的证据）
  if (data.report && data.report.claim_reports.length > 0) {
    lines.push('## 证据链');
    lines.push('');

    data.report.claim_reports.forEach((cr) => {
      lines.push(`### ${cr.claim.claim_id}: ${cr.claim.claim_text}`);
      lines.push('');
      lines.push(`**最终立场**: ${zhStance(cr.final_stance)}`);
      lines.push('');

      if (cr.evidences.length === 0) {
        lines.push('*暂无对齐证据*');
        lines.push('');
        return;
      }

      cr.evidences.forEach((e, idx) => {
        const isSummary = e.source_type === 'web_summary';
        const displayTitle = isSummary && e.summary ? zhText(e.summary) : zhText(e.title);
        lines.push(`#### 证据 ${idx + 1}: ${displayTitle} ${isSummary ? '*(聚合)*' : ''}`);
        lines.push('');
        lines.push('| 属性 | 值 |');
        lines.push('|------|-----|');
        lines.push(`| 立场 | ${zhStance(e.stance)} |`);
        lines.push(`| 来源 | ${e.source} |`);
        lines.push(`| 来源类型 | ${zhSourceType(e.source_type)} |`);
        lines.push(`| 权重 | ${e.source_weight.toFixed(2)} |`);
        if (e.domain) {
          lines.push(`| 领域 | ${zhDomain(e.domain)} |`);
        }
        if (e.is_authoritative) {
          lines.push(`| 权威来源 | 是 |`);
        }
        if (e.alignment_confidence !== undefined && e.alignment_confidence !== null) {
          lines.push(`| 对齐置信度 | ${e.alignment_confidence.toFixed(2)} |`);
        }
        lines.push('');

        if (e.summary && !isSummary) {
          lines.push(`**摘要**: ${zhText(e.summary)}`);
          lines.push('');
        }
        if (e.alignment_rationale) {
          lines.push(`**对齐理由**: ${zhText(e.alignment_rationale)}`);
          lines.push('');
        }
        if (isSummary && e.source_urls && e.source_urls.length > 0) {
          lines.push(`**来源链接** (${e.source_urls.length}条):`);
          lines.push('');
          e.source_urls.forEach((linkUrl, linkIdx) => {
            lines.push(`${linkIdx + 1}. [${linkUrl}](${linkUrl})`);
          });
          lines.push('');
        } else {
          lines.push(`**链接**: [${e.url}](${e.url})`);
          lines.push('');
        }
      });
    });
  } else if (data.evidences.length > 0) {
    // 回退：使用原始证据（未对齐）
    lines.push('## 证据链');
    lines.push('');
    lines.push('*注：以下为原始检索证据，未经过对齐处理*');
    lines.push('');
    
    const byClaim = new Map<string, EvidenceItem[]>();
    data.evidences.forEach((e) => {
      const key = e.claim_id || 'unknown';
      const list = byClaim.get(key) ?? [];
      list.push(e);
      byClaim.set(key, list);
    });

    const claimTextMap = new Map<string, string>();
    data.claims.forEach((c) => {
      claimTextMap.set(c.claim_id, c.claim_text);
    });

    byClaim.forEach((items, claimId) => {
      const claimText = claimTextMap.get(claimId) ?? '未关联到具体主张';
      lines.push(`### ${claimId}: ${claimText}`);
      lines.push('');

      items.forEach((e, idx) => {
        lines.push(`#### 证据 ${idx + 1}: ${zhText(e.title)}`);
        lines.push('');
        lines.push('| 属性 | 值 |');
        lines.push('|------|-----|');
        lines.push(`| 立场 | ${zhStance(e.stance)} |`);
        lines.push(`| 来源 | ${e.source} |`);
        lines.push(`| 来源类型 | ${zhSourceType(e.source_type)} |`);
        lines.push(`| 权重 | ${e.source_weight.toFixed(2)} |`);
        if (e.domain) {
          lines.push(`| 领域 | ${zhDomain(e.domain)} |`);
        }
        lines.push('');

        if (e.summary) {
          lines.push(`**摘要**: ${zhText(e.summary)}`);
          lines.push('');
        }
        lines.push(`**链接**: [${e.url}](${e.url})`);
        lines.push('');
      });
    });
  }

  // 综合报告
  if (data.report) {
    lines.push('## 综合报告');
    lines.push('');
    lines.push(`| 项目 | 值 |`);
    lines.push(`|------|-----|`);
    lines.push(`| 风险评级 | ${zhRiskLabel(data.report.risk_label)}（${zhRiskLevel(data.report.risk_level)}风险）|`);
    lines.push(`| 风险分数 | ${data.report.risk_score} |`);
    lines.push(`| 识别场景 | ${zhScenario(data.report.detected_scenario)} |`);
    lines.push(`| 证据覆盖域 | ${data.report.evidence_domains.map((d) => zhDomain(d)).join('、') || '暂无'} |`);
    lines.push('');
    lines.push(`**摘要**: ${zhText(data.report.summary)}`);
    lines.push('');
    
    if (data.report.suspicious_points.length > 0) {
      lines.push('**可疑点**:');
      lines.push('');
      data.report.suspicious_points.forEach((p) => {
        lines.push(`- ${zhText(p)}`);
      });
      lines.push('');
    }

    // 主张级结论
    if (data.report.claim_reports.length > 0) {
      lines.push('### 主张级结论');
      lines.push('');
      data.report.claim_reports.forEach((cr) => {
        lines.push(`#### ${cr.claim.claim_id}`);
        lines.push('');
        lines.push(`**主张**: ${cr.claim.claim_text}`);
        lines.push('');
        lines.push(`**最终立场**: ${zhStance(cr.final_stance)}`);
        lines.push('');
        if (cr.notes.length > 0) {
          lines.push('**备注**:');
          lines.push('');
          cr.notes.forEach((n) => {
            lines.push(`- ${zhText(n)}`);
          });
          lines.push('');
        }
      });
    }
  }

  // 舆情预演
  if (data.simulation) {
    lines.push('## 舆情预演');
    lines.push('');

    // 情绪分布
    lines.push('### 情绪分布');
    lines.push('');
    const emotions = Object.entries(data.simulation.emotion_distribution);
    if (emotions.length > 0) {
      lines.push('| 情绪 | 占比 |');
      lines.push('|------|------|');
      emotions.forEach(([k, v]) => {
        lines.push(`| ${k} | ${(v * 100).toFixed(1)}% |`);
      });
      lines.push('');
    }

    // 立场分布
    lines.push('### 立场分布');
    lines.push('');
    const stances = Object.entries(data.simulation.stance_distribution);
    if (stances.length > 0) {
      lines.push('| 立场 | 占比 |');
      lines.push('|------|------|');
      stances.forEach(([k, v]) => {
        lines.push(`| ${k} | ${(v * 100).toFixed(1)}% |`);
      });
      lines.push('');
    }

    // 叙事分支
    if (data.simulation.narratives.length > 0) {
      lines.push('### 叙事分支');
      lines.push('');
      data.simulation.narratives.forEach((n, i) => {
        lines.push(`${i + 1}. **${zhText(n.title)}** (${(n.probability * 100).toFixed(0)}%)`);
        lines.push(`   - 立场: ${n.stance}`);
        lines.push(`   - 触发词: ${n.trigger_keywords.join(', ') || '无'}`);
        lines.push(`   - 代表言论: ${zhText(n.sample_message)}`);
        lines.push('');
      });
    }

    // 引爆点
    if (data.simulation.flashpoints.length > 0) {
      lines.push('### 引爆点');
      lines.push('');
      data.simulation.flashpoints.forEach((f) => {
        lines.push(`- ⚠️ ${zhText(f)}`);
      });
      lines.push('');
    }

    // 应对建议
    lines.push('### 应对建议');
    lines.push('');
    if (data.simulation.suggestion?.summary) {
      lines.push(`**${zhText(data.simulation.suggestion.summary)}**`);
      lines.push('');
      if (data.simulation.suggestion.actions?.length > 0) {
        lines.push('| 优先级 | 类别 | 行动 | 时间 | 责任方 |');
        lines.push('|--------|------|------|------|--------|');
        data.simulation.suggestion.actions.forEach((action) => {
          const priorityLabels: Record<string, string> = { urgent: '紧急', high: '高', medium: '中' };
          const categoryLabels: Record<string, string> = { official: '官方', media: '媒体', platform: '平台', user: '用户' };
          lines.push(
            `| ${priorityLabels[action.priority] || action.priority} | ${categoryLabels[action.category] || action.category} | ${zhText(action.action)} | ${action.timeline || '-'} | ${action.responsible || '-'} |`
          );
        });
      }
    }
    lines.push('');
  }

  // 应对内容（澄清稿/FAQ/平台话术）
  // 放置在“舆情预演 → 应对建议”之后，便于阅读：先看风险/证据/报告/预演，再看可直接使用的应对话术
  if (data.content) {
    lines.push('## 应对内容');
    lines.push('');

    const primary = resolvePrimaryClarification(data.content);
    const allClarifications = data.content.clarifications ?? [];

    if (primary) {
      lines.push(`### 澄清稿（主稿：${primary.style}）`);
      lines.push('');
      lines.push('#### 短版');
      lines.push('');
      lines.push(primary.content.short);
      lines.push('');
      lines.push('#### 中版');
      lines.push('');
      lines.push(primary.content.medium);
      lines.push('');
      lines.push('#### 长版');
      lines.push('');
      lines.push(primary.content.long);
      lines.push('');
    }

    const others = allClarifications.filter((v) => v.id !== primary?.id);
    if (others.length > 0) {
      lines.push('### 澄清稿（其他版本）');
      lines.push('');
      others
        .sort((a, b) => (b.generated_at || '').localeCompare(a.generated_at || ''))
        .forEach((v, idx) => {
          lines.push(`#### 版本 ${idx + 1}（${v.style}）`);
          lines.push('');
          lines.push(v.content.medium);
          lines.push('');
        });
    }

    if (data.content.faq && data.content.faq.length > 0) {
      lines.push('### FAQ');
      lines.push('');
      data.content.faq.forEach((item, idx) => {
        lines.push(`- **Q${idx + 1}**: ${item.question}`);
        lines.push(`  - ${item.answer}`);
      });
      lines.push('');
    }

    if (data.content.platform_scripts && data.content.platform_scripts.length > 0) {
      lines.push('### 多平台话术');
      lines.push('');
      data.content.platform_scripts.forEach((s) => {
        lines.push(`#### ${s.platform}`);
        lines.push('');
        lines.push(s.content);
        lines.push('');
      });
    }
  }

  lines.push('---');
  lines.push('');
  lines.push('*本报告由 TruthCast 智能研判台自动生成，仅供辅助决策参考。*');

  return lines.join('\n');
}
