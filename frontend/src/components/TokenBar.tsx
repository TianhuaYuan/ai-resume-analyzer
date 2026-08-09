import { useMemo } from "react";

/**
 * TokenBar — Token 使用堆叠条形图（借鉴 Hermes TokenBar）。
 *
 * 将 prompt/completion token 分解为可视化的堆叠色条 + 数值标注，
 * 用于问答消息的 token 消耗可视化。
 *
 * 支持段：Input（prompt）/ Output（completion）；预留 reasoning/cacheRead
 * （后端上报后即可显示）。各段宽度按占总量的比例。
 */

interface TokenSegment {
  value: number;
  color: string;
  label: string;
}

interface TokenBarProps {
  /** 总 token 数（total）；若缺失则由 prompt+completion 求和 */
  total?: number;
  prompt?: number;
  completion?: number;
  /** 是否显示数值标签（默认 true） */
  showLabels?: boolean;
  className?: string;
}

// 段配色（与 UsageDialog 的 brand/amber 体系协调）
const SEGMENTS: TokenSegment[] = [
  { value: 0, color: "#60a5fa", label: "Input" }, // blue-400
  { value: 0, color: "#c084fc", label: "Output" }, // purple-400
];

export default function TokenBar({
  total,
  prompt = 0,
  completion = 0,
  showLabels = true,
  className = "",
}: TokenBarProps) {
  const resolved = useMemo(() => {
    const input = Math.max(0, prompt);
    const output = Math.max(0, completion);
    const sum = total ?? input + output;
    return {
      input,
      output,
      sum: Math.max(1, sum), // 防除零
      hasAny: input > 0 || output > 0,
    };
  }, [total, prompt, completion]);

  if (!resolved.hasAny) return null;

  const { input, output, sum } = resolved;
  const inputPct = (input / sum) * 100;
  const outputPct = (output / sum) * 100;

  return (
    <div className={`w-full ${className}`}>
      <div className="relative flex min-h-[0.4rem] w-full items-stretch overflow-hidden rounded-full bg-[var(--color-bg-secondary)]">
        {input > 0 && (
          <div
            title={`Input ${input.toLocaleString()}`}
            className="transition-all duration-500"
            style={{ width: `${inputPct}%`, backgroundColor: SEGMENTS[0].color }}
          />
        )}
        {output > 0 && (
          <div
            title={`Output ${output.toLocaleString()}`}
            className="transition-all duration-500"
            style={{ width: `${outputPct}%`, backgroundColor: SEGMENTS[1].color }}
          />
        )}
      </div>
      {showLabels && (
        <div className="mt-1 flex items-center justify-between text-[10px] text-[var(--color-text-muted)] tabular-nums">
          <span className="flex items-center gap-1">
            <span className="inline-block w-1.5 h-1.5 rounded-full" style={{ backgroundColor: SEGMENTS[0].color }} />
            Input {input.toLocaleString()}
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block w-1.5 h-1.5 rounded-full" style={{ backgroundColor: SEGMENTS[1].color }} />
            Output {output.toLocaleString()}
          </span>
          <span>共 {sum.toLocaleString()}</span>
        </div>
      )}
    </div>
  );
}
