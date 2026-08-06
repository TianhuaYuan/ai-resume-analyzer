/**
 * AgentCardRouter — 消息流内卡片通用分发（Generative UI 思路）。
 *
 * 根据 agentSteps 中的工具调用结果，决定渲染哪种卡片：
 * - jd_match → JDMatchReport（结构化匹配报告）
 * - 默认 → MarkdownRenderer（纯文本/markdown）
 */

import type { AgentStep } from "../api/qa";
import type { JdReport, MatchJDResult } from "../api/resumes";
import JDMatchReport from "./JDMatchReport";
import NegotiationBriefCard, { type NegotiationBrief } from "./NegotiationBriefCard";
import MarkdownRenderer from "./MarkdownRenderer";

interface AgentCardRouterProps {
  steps: AgentStep[];
  answer: string;
  streaming: boolean;
}

/**
 * 从 agentSteps 中提取 JD 匹配结构化载荷。
 *
 * 逻辑：
 * 1. 找到 tool_call 中 name === "jd_match" 的步骤 → 取其 id
 * 2. 找到 tool_result 中 id 匹配的步骤 → 取其 result
 * 3. 正则提取 <match_result>{...}</match_result> 块 → 解析 JSON
 */
export function extractJdMatchPayload(steps: AgentStep[]): MatchJDResult | null {
  // 找到 jd_match 的 tool_call 步骤
  const callStep = steps.find(
    (s) => s.type === "tool_call" && s.name === "jd_match"
  );
  if (!callStep?.id) return null;

  // 找到对应的 tool_result 步骤（id 匹配）
  const resultStep = steps.find(
    (s) => s.type === "tool_result" && s.id === callStep.id
  );
  if (!resultStep?.result && !resultStep?.detail) return null;

  // 从 result 或 detail 中提取 <match_result> 块
  const text = resultStep.result ?? resultStep.detail ?? "";
  const match = text.match(/<match_result>([\s\S]*?)<\/match_result>/);
  if (!match?.[1]) return null;

  try {
    const parsed = JSON.parse(match[1]);
    // I1: 提取 <jd_report> 6-block 报告（best-effort，缺失不影响 match 卡片）
    let report: JdReport | null = null;
    const reportMatch = text.match(/<jd_report>([\s\S]*?)<\/jd_report>/);
    if (reportMatch?.[1]) {
      try {
        report = JSON.parse(reportMatch[1]) as JdReport;
      } catch {
        report = null;
      }
    }
    return {
      resume_id: parsed.resume_id ?? 0,
      analysis: parsed.analysis ?? "",
      scores: parsed.scores ?? null,
      dims: parsed.dims ?? null,
      matched_keywords: parsed.matched_keywords ?? [],
      missing_keywords: parsed.missing_keywords ?? [],
      gaps: parsed.gaps ?? [],
      report: report ?? parsed.report ?? null,
    };
  } catch {
    return null;
  }
}

/**
 * 从 tool_result 中提取 <negotiation_brief>{...}</negotiation_brief> 块（I3）。
 */
export function extractNegotiationBrief(steps: AgentStep[]): NegotiationBrief | null {
  const callStep = steps.find((s) => s.type === "tool_call" && s.name === "negotiation_brief");
  if (!callStep?.id) return null;
  const resultStep = steps.find((s) => s.type === "tool_result" && s.id === callStep.id);
  const text = resultStep?.result ?? resultStep?.detail ?? "";
  const match = text.match(/<negotiation_brief>([\s\S]*?)<\/negotiation_brief>/);
  if (!match?.[1]) return null;
  try {
    return JSON.parse(match[1]) as NegotiationBrief;
  } catch {
    return null;
  }
}

export default function AgentCardRouter({
  steps,
  answer,
  streaming,
}: AgentCardRouterProps) {
  // 流式期间：不尝试渲染卡片，直接走 markdown
  if (streaming) {
    return (
      <MarkdownRenderer>
        {answer}
      </MarkdownRenderer>
    );
  }

  // 尝试提取 JD 匹配载荷（I1 6-block 报告一并带出）
  const jdPayload = extractJdMatchPayload(steps);

  if (jdPayload) {
    return <JDMatchReport result={jdPayload} />;
  }

  // I3: 谈薪简报卡片
  const brief = extractNegotiationBrief(steps);
  if (brief) {
    return <NegotiationBriefCard brief={brief} />;
  }

  // 默认：markdown 渲染
  return (
    <MarkdownRenderer>
      {answer}
    </MarkdownRenderer>
  );
}
