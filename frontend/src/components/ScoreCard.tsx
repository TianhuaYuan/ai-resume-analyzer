/**
 * ScoreCard — 简历四维评分可视化（复制自 Magic-Resume ArtifactCanvas + DeepInterview score-bento）。
 *
 * - scoreBandKey：档位阈值 >=85 excellent / >=70 good / >=50 medium / else needsWork
 *   （Magic-Resume ArtifactCanvas.tsx L53-58 原版逻辑，后端 ScoreDetail.band 同源派生）
 * - SCORE_DIMENSIONS：四维固定色序（Magic-Resume FIT_DIMENSIONS L30-35 对照）
 * - 总分 hero 大数字（DeepInterview score-bento 风格）+ 四维彩条进度（ArtifactCanvas ScoreView）
 */
import { CheckCircle, TrendUp } from "@phosphor-icons/react";
import type { ScoreDetail } from "../api/resumes";

export type ScoreBand = "excellent" | "good" | "medium" | "needsWork";

/** 档位判定（与后端 schemas/resume.py derive_band 同源阈值，Magic-Resume scoreBandKey 对照） */
export function scoreBandKey(score: number): ScoreBand {
  if (score >= 85) return "excellent";
  if (score >= 70) return "good";
  if (score >= 50) return "medium";
  return "needsWork";
}

export const BAND_META: Record<
  ScoreBand,
  { label: string; className: string; bar: string }
> = {
  excellent: { label: "优秀", className: "text-success", bar: "bg-success" },
  good: { label: "良好", className: "text-sky-400", bar: "bg-sky-400" },
  medium: { label: "中等", className: "text-warning", bar: "bg-warning" },
  needsWork: { label: "待提升", className: "text-rose-400", bar: "bg-rose-400" },
};

/** 四维固定色序（Magic-Resume FIT_DIMENSIONS 对照） */
const SCORE_DIMENSIONS: { key: keyof ScoreDetail; label: string; color: string }[] = [
  { key: "ats_match", label: "ATS 匹配", color: "#38bdf8" },
  { key: "keyword_coverage", label: "关键词覆盖", color: "#a78bfa" },
  { key: "skill_density", label: "技能密度", color: "#34d399" },
  { key: "overall", label: "综合评价", color: "#fbbf24" },
];

function clamp(v: number): number {
  return Math.max(0, Math.min(100, Number.isFinite(v) ? v : 0));
}

export default function ScoreCard({ scores }: { scores: ScoreDetail }) {
  const band = scoreBandKey(scores.overall ?? 0);
  const meta = BAND_META[band];
  const overall = clamp(scores.overall ?? 0);

  return (
    <div className="space-y-5">
      {/* 总分 hero（DeepInterview score-bento 大数字风格） */}
      <div className="flex items-center gap-5">
        <div className="relative w-20 h-20 shrink-0">
          <svg viewBox="0 0 80 80" className="w-20 h-20 -rotate-90">
            <circle cx="40" cy="40" r="34" fill="none" stroke="var(--color-bg-secondary)" strokeWidth="7" />
            <circle
              cx="40"
              cy="40"
              r="34"
              fill="none"
              stroke={SCORE_DIMENSIONS[3].color}
              strokeWidth="7"
              strokeLinecap="round"
              strokeDasharray={`${(overall / 100) * 2 * Math.PI * 34} ${2 * Math.PI * 34}`}
              className="transition-all duration-700"
            />
          </svg>
          <span className="absolute inset-0 flex items-center justify-center text-xl font-semibold tabular-nums text-[var(--color-text)]">
            {Math.round(overall)}
          </span>
        </div>
        <div className="min-w-0">
          <div className={`text-[15px] font-medium ${meta.className}`}>
            {meta.label}
            <span className="text-xs text-[var(--color-text-muted)] ml-2">综合评分</span>
          </div>
          <p className="text-xs text-[var(--color-text-muted)] mt-1 leading-relaxed">
            四维加权：ATS 匹配 / 关键词覆盖 / 技能密度
          </p>
        </div>
      </div>

      {/* 四维彩条（ArtifactCanvas ScoreView 对照：固定色序 + 分数右对齐） */}
      <div className="space-y-3.5">
        {SCORE_DIMENSIONS.map((dim) => {
          const value = clamp(scores[dim.key] ?? 0);
          return (
            <div key={dim.key} className="flex items-center gap-3">
              <span
                className="w-1.5 h-1.5 rounded-full shrink-0"
                style={{ background: dim.color }}
                aria-hidden="true"
              />
              <span className="text-xs text-[var(--color-text-secondary)] w-20 shrink-0">
                {dim.label}
              </span>
              <div className="flex-1 h-1.5 rounded-full bg-[var(--color-bg-secondary)] overflow-hidden">
                <div
                  className="h-full rounded-full transition-all duration-700"
                  style={{ background: dim.color, width: `${value}%` }}
                />
              </div>
              <span className="text-xs font-medium text-[var(--color-text)] w-7 text-right tabular-nums">
                {Math.round(value)}
              </span>
            </div>
          );
        })}
      </div>

      {/* 解读提示 */}
      <div className="flex items-start gap-2 rounded-list bg-[var(--color-bg-secondary)]/60 px-3.5 py-3">
        {overall >= 70 ? (
          <CheckCircle size={15} className="text-success mt-0.5 shrink-0" weight="fill" />
        ) : (
          <TrendUp size={15} className="text-warning mt-0.5 shrink-0" />
        )}
        <p className="text-xs text-[var(--color-text-muted)] leading-relaxed">
          {overall >= 85
            ? "简历整体质量优秀，可直接用于投递，可针对目标岗位微调关键词。"
            : overall >= 70
              ? "简历整体质量良好，补充量化成果与关键词覆盖可进一步提升。"
              : overall >= 50
                ? "简历中等水平，建议优先补充量化指标与岗位关键词。"
                : "简历待提升，建议按维度逐项优化后重新评估。"}
        </p>
      </div>
    </div>
  );
}
