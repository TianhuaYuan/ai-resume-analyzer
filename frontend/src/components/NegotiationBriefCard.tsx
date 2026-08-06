/**
 * NegotiationBriefCard — 谈薪简报卡片（I3）。
 *
 * 渲染 negotiation_brief 工具输出的 <negotiation_brief> JSON 块：
 * 总包锚定 / 谈判底线 / 地理折扣 / 谈薪话术。
 */
import { Money, ShieldCheck, MapPin, ChatCircle } from "@phosphor-icons/react";

export interface NegotiationBrief {
  target_position?: string;
  anchor?: string;
  anchor_floor?: string;
  geo?: { city?: string; factor?: number; note?: string };
  scripts?: string[];
  rationale?: string;
  generated_by?: string;
}

export default function NegotiationBriefCard({ brief }: { brief: NegotiationBrief }) {
  return (
    <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/[0.03] overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-2.5 bg-emerald-500/10">
        <Money size={15} weight="bold" className="text-emerald-600 shrink-0" />
        <span className="text-sm font-medium text-[var(--color-text)]">谈薪简报</span>
        {brief.target_position && (
          <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-emerald-500/10 text-emerald-600 font-medium">
            {brief.target_position}
          </span>
        )}
        {brief.generated_by === "template" && (
          <span className="text-[10px] text-[var(--color-text-muted)]" title="LLM 生成失败，使用确定性估算模板">
            估算模板
          </span>
        )}
      </div>

      <div className="px-4 py-3 space-y-3">
        {/* 总包锚定 + 底线 */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
          <div className="rounded-lg bg-[var(--color-bg-secondary)] p-2.5">
            <div className="flex items-center gap-1 text-[10px] font-medium text-[var(--color-text-muted)] mb-1">
              <ShieldCheck size={11} className="text-emerald-600" />
              总包锚定
            </div>
            <p className="text-sm font-semibold text-[var(--color-text)] leading-snug">
              {brief.anchor || "—"}
            </p>
          </div>
          <div className="rounded-lg bg-[var(--color-bg-secondary)] p-2.5">
            <div className="text-[10px] font-medium text-[var(--color-text-muted)] mb-1">谈判底线</div>
            <p className="text-sm font-semibold text-emerald-600 leading-snug">
              {brief.anchor_floor || "—"}
            </p>
          </div>
        </div>

        {/* 地理折扣 */}
        {brief.geo && (
          <div className="flex items-center gap-2 text-xs text-[var(--color-text-secondary)]">
            <MapPin size={13} className="text-brand shrink-0" />
            <span className="font-medium">{brief.geo.city || "未指定"}</span>
            <span className="text-[var(--color-text-muted)]">系数 {brief.geo.factor ?? 1.0}</span>
            {brief.geo.note && <span className="text-[var(--color-text-muted)]">· {brief.geo.note}</span>}
          </div>
        )}

        {/* 谈薪话术 */}
        {brief.scripts && brief.scripts.length > 0 && (
          <div>
            <div className="flex items-center gap-1.5 text-[11px] font-medium text-[var(--color-text-muted)] mb-1.5">
              <ChatCircle size={12} className="text-emerald-600" />
              谈薪话术
            </div>
            <div className="space-y-1.5">
              {brief.scripts.map((s, i) => (
                <p
                  key={i}
                  className="text-xs text-[var(--color-text-secondary)] leading-relaxed bg-[var(--color-bg-secondary)] rounded-lg px-3 py-2"
                >
                  {s}
                </p>
              ))}
            </div>
          </div>
        )}

        {brief.rationale && (
          <p className="text-[11px] text-[var(--color-text-muted)] italic">{brief.rationale}</p>
        )}
      </div>
    </div>
  );
}
