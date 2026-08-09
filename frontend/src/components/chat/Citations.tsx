import SourceBlock from "./SourceBlock";
import type { DiagnosisSource } from "./DiagnosisCard";

interface CitationsProps {
  sources?: DiagnosisSource[];
}

/**
 * Citations — 普通问答消息的来源引用（Open WebUI Citations 风格）。
 *
 * 任何有 sources 的消息（非诊断卡分支）在答案下方渲染"查看 N 条来源"折叠，
 * 展开后为编号 [n] + section 标签 + 字符区间 + 原文片段。
 * 无有效来源时不渲染。
 */
export default function Citations({ sources }: CitationsProps) {
  if (!sources || sources.length === 0) return null;
  const items = sources.filter((s) => s && typeof s.text === "string" && s.text.length > 0);
  if (items.length === 0) return null;
  return (
    <SourceBlock
      sources={sources}
      title={`查看 ${items.length} 条来源`}
      numbered
    />
  );
}
