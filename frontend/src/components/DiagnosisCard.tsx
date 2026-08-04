/**
 * DiagnosisCard — 简历诊断结构化卡片（E1 可溯源诊断）。
 *
 * 当 Agent 回答来自 diagnose_resume 工具（或文本含「## 评分」/ScoreDetail 结构）时，
 * 将纯 markdown 渲染升级为三层：
 *   1. 四维评分卡（ScoreCard：ATS匹配 / 关键词覆盖 / 技能密度 / 综合评价）
 *   2. 诊断结论 + 建议（markdown 原文，剥离已被卡片可视化的「评分」段）
 *   3. 可溯源「来源原文」折叠区（每条：section 标签 + 字符区间 + 文本片段，点击展开上下文）
 *
 * 评分提取失败 → 整体回退纯 markdown（降级，不破坏现有渲染路径）。
 * 评分解析逻辑与后端 services/analyze_service.py _parse_scores 同源对齐：
 * JSON-first → Markdown 表格 → JSON 键值 → 键值对/分节标题 → 裸数字序列，
 * 需提取到 4 个 0-100 的合法分数（年份/ID 等 >100 数字会被过滤）。
 */
import { memo, useState } from "react";
import { CaretRight, CaretDown } from "@phosphor-icons/react";
import ScoreCard from "./ScoreCard";
import MarkdownRenderer from "./MarkdownRenderer";
import type { ScoreDetail } from "../api/resumes";
import type { SourceItem, AgentStep } from "../api/qa";

/**
 * 后端正在并行扩展 sources：{text} → {text, section?, start_char?, end_char?}。
 * section = 分节名（如「工作经历」），start_char/end_char = 原文中的字符区间。
 */
export interface DiagnosisSource extends SourceItem {
  section?: string;
  start_char?: number;
  end_char?: number;
}

/** 判断一条消息是否应进入诊断卡片分支（供 QAPage 渲染时调用）。 */
export function isDiagnosisMessage(msg: {
  answer: string;
  agent_steps?: AgentStep[];
}): boolean {
  // 信号 1（实时消息）：工具序列中包含 diagnose_resume 调用
  const calledDiagnose = (msg.agent_steps ?? []).some(
    (s) => s.type === "tool_call" && s.name === "diagnose_resume"
  );
  if (calledDiagnose) return true;
  // 信号 2（历史消息，无 agent_steps）：回答文本含「## 评分」标题或 ScoreDetail JSON 键
  return /##\s*评分|"ats_match"\s*:/.test(msg.answer ?? "");
}

/** 提取「## 评分」标题之后的评分块文本（到下一个 "## " 标题或文末）。无标题返回 null。 */
function extractScoreSection(answer: string): string | null {
  const m = answer.match(/^##\s*评分\s*$/m);
  if (!m || m.index == null) return null;
  const rest = answer.slice(m.index + m[0].length);
  const nextHeading = rest.search(/^\s*##\s/m);
  return (nextHeading === -1 ? rest : rest.slice(0, nextHeading)).trim();
}

/** 从回答中剥离「## 评分」标题及其评分块，保留其余诊断结论/建议正文。 */
function stripScoreSection(answer: string, scoreSection: string): string {
  const headingIdx = answer.search(/^##\s*评分\s*$/m);
  if (headingIdx === -1) return answer;
  const contentStart = answer.indexOf(scoreSection, headingIdx);
  const contentEnd =
    contentStart === -1 ? answer.length : contentStart + scoreSection.length;
  return (answer.slice(0, headingIdx) + answer.slice(contentEnd))
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

/** 收集正则全部匹配，返回各捕获组 1 的整数列表。 */
function collectNums(re: RegExp, text: string): number[] {
  const out: number[] = [];
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    out.push(parseInt(m[1], 10));
  }
  return out;
}

/** JSON-first：完整 ScoreDetail 对象 → 校验后直接返回。 */
function parseJsonScore(text: string): ScoreDetail | null {
  try {
    const data: unknown = JSON.parse(text.trim());
    if (!data || typeof data !== "object" || Array.isArray(data)) return null;
    const obj = data as Record<string, unknown>;
    if (!["ats_match", "keyword_coverage", "skill_density", "overall"].every(
      (k) => k in obj,
    )) {
      return null;
    }
    const vals = ["ats_match", "keyword_coverage", "skill_density", "overall"].map((k) => {
      const n = Number(obj[k]);
      return Number.isFinite(n) && n >= 0 && n <= 100 ? Math.round(n) : -1;
    });
    if (vals.some((v) => v < 0)) return null;
    return {
      ats_match: vals[0],
      keyword_coverage: vals[1],
      skill_density: vals[2],
      overall: vals[3],
    };
  } catch {
    return null; // 非 JSON → 正则降级
  }
}

/**
 * 从评分文本中提取四维分数（后端 _parse_scores 的 TS 移植）。
 * 非法分数（>100，如年份/ID）过滤后不足 4 个 → null。
 */
function parseScores(text: string): ScoreDetail | null {
  if (!text || !text.trim()) return null;

  const json = parseJsonScore(text);
  if (json) return json;

  // 1. Markdown 表格（最常见）：| ATS | 75 |
  let nums = collectNums(
    /\|\s*(?:ATS|关键词|技能密度|综合|评价)\s*\|\s*(\d+)\s*\|/g,
    text,
  );

  // 2. JSON 键值（正则版）："keyword_coverage": 68
  if (nums.length === 0) {
    nums = collectNums(
      /"(?:ats_match|keyword_coverage|skill_density|overall)"\s*:\s*(\d+)/g,
      text,
    );
  }

  // 3. 键值对 / 分节标题（中英文标签，标签后 80 字符内取首个数字）
  if (nums.length === 0) {
    const labelRe =
      /(?:ATS\s*匹配率|关键词覆盖率|技能密度|综合评价|ATS\s*score|keyword\s*score|skill\s*score|overall\s*score|ATS\s*得分|关键词\s*得分|技能\s*得分|综合\s*得分)/g;
    const found: number[] = [];
    let m: RegExpExecArray | null;
    while ((m = labelRe.exec(text)) !== null) {
      const tail = text.slice(m.index + m[0].length, m.index + m[0].length + 80);
      const num = tail.match(/\d+/);
      if (num) found.push(parseInt(num[0], 10));
    }
    nums = found;
  }

  // 4. 兜底：裸数字序列（如 "85/100\n90/100\n78/100\n82/100"）
  if (nums.length === 0) {
    nums = collectNums(/(?:^|\D)(\d{1,3})(?:\/100|分)?/g, text);
  }

  // 过滤非法分数（年份/ID 等 >100 的数字不是分数），不足 4 个 → 放弃
  const valid = nums.filter((n) => n >= 0 && n <= 100);
  if (valid.length < 4) return null;

  return {
    ats_match: valid[0],
    keyword_coverage: valid[1],
    skill_density: valid[2],
    overall: valid[3],
  };
}

/** 可溯源「来源原文」折叠区：每条 section 标签 + 字符区间 + 文本片段，点击展开上下文。 */
function SourceBlock({ sources }: { sources: DiagnosisSource[] }) {
  const [open, setOpen] = useState(false);
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);
  const items = sources.filter((s) => s && typeof s.text === "string" && s.text.length > 0);
  if (items.length === 0) return null;

  return (
    <div className="rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-secondary)]/40 overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between gap-2 px-3.5 py-2.5 text-xs font-medium
          text-[var(--color-text-secondary)] hover:bg-black/[0.03] transition-colors cursor-pointer"
      >
        <span className="inline-flex items-center gap-1.5 min-w-0">
          <span className="text-brand shrink-0">📎</span>
          <span className="truncate">来源原文</span>
          <span className="text-[10px] text-[var(--color-text-muted)] shrink-0">
            {items.length} 条
          </span>
        </span>
        {open ? (
          <CaretDown size={13} className="shrink-0" aria-hidden="true" />
        ) : (
          <CaretRight size={13} className="shrink-0" aria-hidden="true" />
        )}
      </button>
      {open && (
        <div className="px-3.5 pb-3 space-y-2">
          {items.map((s, i) => {
            const expanded = expandedIdx === i;
            return (
              <button
                key={i}
                onClick={() => setExpandedIdx(expanded ? null : i)}
                className="w-full text-left rounded-lg border border-[var(--color-border)]
                  bg-white/60 p-2.5 transition-colors cursor-pointer hover:border-brand/30"
              >
                <div className="flex items-center gap-1.5 flex-wrap">
                  {s.section ? (
                    <span className="px-1.5 py-0.5 rounded-md text-[10px] font-medium text-brand
                      bg-brand/10 border border-brand/15">
                      {s.section}
                    </span>
                  ) : (
                    <span className="px-1.5 py-0.5 rounded-md text-[10px] font-medium
                      text-[var(--color-text-muted)] bg-[var(--color-bg-secondary)] border border-[var(--color-border)]">
                      片段 {i + 1}
                    </span>
                  )}
                  {typeof s.score === "number" && (
                    <span className="text-[10px] text-[var(--color-text-muted)]">
                      相关度 {Math.round(s.score * 100)}%
                    </span>
                  )}
                  {s.start_char != null && s.end_char != null && (
                    <span className="text-[10px] font-mono text-[var(--color-text-muted)]">
                      字符 {s.start_char}–{s.end_char}
                    </span>
                  )}
                  <span className="ml-auto shrink-0 text-[var(--color-text-muted)]">
                    {expanded ? (
                      <CaretDown size={12} aria-hidden="true" />
                    ) : (
                      <CaretRight size={12} aria-hidden="true" />
                    )}
                  </span>
                </div>
                <p
                  className={`mt-1.5 text-xs text-[var(--color-text-secondary)] leading-relaxed whitespace-pre-wrap break-words ${
                    expanded ? "" : "line-clamp-3"
                  }`}
                >
                  {s.text}
                </p>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

function DiagnosisCardImpl({
  answer,
  sources,
}: {
  answer: string;
  sources?: DiagnosisSource[];
}) {
  // 评分提取失败 → 回退纯 markdown（降级，不破坏现有渲染）
  const scoreSection = extractScoreSection(answer);
  const scores = parseScores(scoreSection ?? answer);
  if (!scores) {
    return <MarkdownRenderer>{answer}</MarkdownRenderer>;
  }

  // 诊断结论 + 建议：剥离已被评分卡可视化的「评分」段
  const body = scoreSection ? stripScoreSection(answer, scoreSection) : answer;

  return (
    <div className="space-y-3">
      {/* 四维评分卡 */}
      <div className="rounded-xl border border-[var(--color-border)] bg-white/70 p-3.5">
        <ScoreCard scores={scores} />
      </div>

      {/* 诊断结论 + 建议 */}
      {body && <MarkdownRenderer>{body}</MarkdownRenderer>}

      {/* 可溯源来源原文 */}
      <SourceBlock sources={sources ?? []} />
    </div>
  );
}

const DiagnosisCard = memo(DiagnosisCardImpl);
export default DiagnosisCard;
