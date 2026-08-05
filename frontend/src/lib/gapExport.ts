/**
 * gapExport — 将 matchJD.gaps 格式化为可复制的"一行一个差距"清单。
 *
 * 纯函数，零 React 依赖。复制到剪贴板由调用组件处理。
 */

export interface GapExportContext {
  /** 简历文件名/标题 */
  resumeName?: string;
  /** JD 文本片段（将被截断到 100 字符） */
  jdSnippet?: string;
}

/**
 * 将 JD 匹配结果格式化为结构化差距清单文本。
 *
 * 输出结构：
 * - 第 1 行：简历名（如有）
 * - 第 2 行：匹配度分数（如有）
 * - 第 3 行：JD 片段预览（如有，截断 100 字符）
 * - 空行分隔
 * - 第 4 行起：每行一条差距（gaps 内嵌换行替换为 " · "）
 *
 * @returns 格式化后的纯文本，无差距时返回 "暂无差距项"。
 */
export function formatGapList(
  result: { scores?: { overall?: number } | null; gaps?: string[] | null },
  ctx?: GapExportContext,
): string {
  const gaps = result.gaps ?? [];
  if (gaps.length === 0) return "暂无差距项";

  const lines: string[] = [];

  // 简历名
  if (ctx?.resumeName) {
    lines.push(`简历：${ctx.resumeName}`);
  }

  // 匹配度
  if (result.scores?.overall != null) {
    lines.push(`匹配度：${result.scores.overall} / 100`);
  }

  // JD 片段
  if (ctx?.jdSnippet) {
    const snippet = ctx.jdSnippet.replace(/\s+/g, " ").trim();
    const truncated = snippet.length > 100 ? snippet.slice(0, 100) + "..." : snippet;
    lines.push(`JD 预览：${truncated}`);
  }

  // 空行分隔（有头部信息时才插入）
  if (lines.length > 0) lines.push("");

  // 差距清单：每条差距占一行，内嵌换行替换为 " · "
  for (const gap of gaps) {
    lines.push(`- ${gap.replace(/[\r\n]+/g, " · ").trim()}`);
  }

  return lines.join("\n");
}
