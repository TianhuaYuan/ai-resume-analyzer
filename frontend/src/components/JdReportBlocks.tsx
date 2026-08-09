/**
 * JdReportBlocks — JD 6-block 求职评估报告（I1）。
 *
 * 渲染 JDMatchTool 生成的 6-block 报告（角色摘要 / CV 匹配表 / 级别策略 /
 * 薪酬市场 / 个性化计划 / 面试故事映射 / Block G 岗位可信度防坑）。
 * 参考 JobMcp report_format.md 的 6-block 结构。
 *
 * Block G（岗位可信度）用 tier 着色：high_confidence 绿 / proceed_with_caution 黄 / suspicious 红。
 */
import { useState } from "react";
import { CircleUser, Table, Target, Banknote, ListChecks, MessagesSquare, ShieldAlert, ChevronDown, ChevronRight } from "lucide-react";
import type { JdReport } from "../api/resumes";

const CRED_TIER_META: Record<string, { label: string; cls: string; icon: string }> = {
  high_confidence: { label: "高可信", cls: "text-success bg-success/10 border-success/30", icon: "🟢" },
  proceed_with_caution: { label: "谨慎投递", cls: "text-warning bg-warning/10 border-warning/30", icon: "🟡" },
  suspicious: { label: "疑似风险", cls: "text-danger bg-danger/10 border-danger/30", icon: "🔴" },
};

function Block({
  title,
  icon: Icon,
  defaultOpen = false,
  children,
}: {
  title: string;
  icon: React.ElementType;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-list border border-[var(--color-border)] overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-2 px-4 py-2.5 bg-[var(--color-bg-secondary)] hover:bg-[var(--color-bg-secondary)] transition-colors cursor-pointer"
      >
        <Icon size={15} strokeWidth={2.25} className="text-brand shrink-0" aria-hidden="true" />
        <span className="text-sm font-medium text-[var(--color-text)] flex-1 text-left">{title}</span>
        {open ? (
          <ChevronDown size={13} strokeWidth={2.25} className="text-[var(--color-text-muted)] shrink-0" />
        ) : (
          <ChevronRight size={13} strokeWidth={2.25} className="text-[var(--color-text-muted)] shrink-0" />
        )}
      </button>
      {open && <div className="px-4 py-3 space-y-2">{children}</div>}
    </div>
  );
}

function Field({ k, v }: { k: string; v?: string | number }) {
  if (v === undefined || v === null || v === "") return null;
  return (
    <div className="flex gap-2 text-xs">
      <span className="text-[var(--color-text-muted)] shrink-0 w-20">{k}</span>
      <span className="text-[var(--color-text-secondary)]">{String(v)}</span>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { label: string; cls: string }> = {
    matched: { label: "匹配", cls: "bg-success/10 text-success" },
    partial: { label: "部分", cls: "bg-warning/10 text-warning" },
    missing: { label: "缺失", cls: "bg-danger/10 text-danger" },
  };
  const cfg = map[status] ?? { label: status, cls: "bg-[var(--color-bg-tertiary)] text-[var(--color-text-muted)]" };
  return (
    <span className={`shrink-0 px-1.5 py-0.5 rounded-full text-[10px] font-medium ${cfg.cls}`}>
      {cfg.label}
    </span>
  );
}

export default function JdReportBlocks({ report }: { report: JdReport }) {
  if (!report) return null;

  const rs = report.role_summary;
  const cv = report.cv_match;
  const ls = report.level_strategy;
  const cm = report.comp_market;
  const pp = report.personalization_plan;
  const stories = report.interview_stories ?? [];
  const cred = report.job_credibility;

  return (
    <div className="space-y-2.5 mt-4 pt-4 border-t border-[var(--color-border)]">
      <div className="flex items-center gap-2">
        <Target size={15} strokeWidth={2.25} className="text-brand" />
        <span className="text-sm font-semibold text-[var(--color-text)]">6-block 求职评估报告</span>
      </div>

      {/* Block A: 角色摘要 */}
      <Block title="角色摘要" icon={CircleUser} defaultOpen>
        <Field k="类型" v={rs?.archetype} />
        <Field k="领域" v={rs?.domain} />
        <Field k="职能" v={rs?.function} />
        <Field k="职级" v={rs?.seniority} />
        <Field k="办公" v={rs?.remote} />
        <Field k="团队" v={rs?.team_size} />
        {rs?.tldr && <p className="text-xs text-[var(--color-text-secondary)] leading-relaxed">{rs.tldr}</p>}
      </Block>

      {/* Block B: CV 匹配表 */}
      <Block title="CV 匹配表" icon={Table}>
        {cv?.table?.length ? (
          <div className="space-y-1.5">
            {cv.table.map((row, i) => (
              <div key={i} className="flex items-start gap-2 text-xs">
                <StatusBadge status={row.status} />
                <div className="min-w-0 flex-1">
                  <div className="text-[var(--color-text)]">{row.jd_requirement}</div>
                  {row.cv_evidence && (
                    <div className="text-[var(--color-text-muted)] mt-0.5">佐证：{row.cv_evidence}</div>
                  )}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-xs text-[var(--color-text-muted)]">无匹配表数据</p>
        )}
        {cv?.gaps?.length ? (
          <div className="pt-2 border-t border-[var(--color-border)] space-y-1.5">
            <div className="text-[11px] font-medium text-[var(--color-text-muted)]">差距</div>
            {cv.gaps.map((g, i) => (
              <div key={i} className="text-xs text-[var(--color-text-secondary)] leading-relaxed">
                <span className="text-warning">{g.type}</span>
                {g.adjacent ? ` · 邻近经验：${g.adjacent}` : ""}
                {g.mitigation ? ` · 缓解：${g.mitigation}` : ""}
              </div>
            ))}
          </div>
        ) : null}
      </Block>

      {/* Block C: 级别策略 */}
      <Block title="级别策略" icon={ListChecks}>
        <Field k="JD 级别" v={ls?.jd_level} />
        <Field k="候选级别" v={ls?.candidate_level} />
        {ls?.sell_senior_plan && (
          <div>
            <div className="text-[11px] font-medium text-[var(--color-text-muted)] mb-1">不撒谎体现资深</div>
            <p className="text-xs text-[var(--color-text-secondary)] leading-relaxed">{ls.sell_senior_plan}</p>
          </div>
        )}
        {ls?.downlevel_plan && (
          <div>
            <div className="text-[11px] font-medium text-[var(--color-text-muted)] mb-1">被降级应对</div>
            <p className="text-xs text-[var(--color-text-secondary)] leading-relaxed">{ls.downlevel_plan}</p>
          </div>
        )}
      </Block>

      {/* Block D: 薪酬市场 */}
      <Block title="薪酬市场" icon={Banknote}>
        <Field k="市场区间" v={cm?.market_range} />
        <Field k="锚定建议" v={cm?.base_hint} />
        {cm?.sources?.length ? (
          <div className="flex flex-wrap gap-1.5">
            {cm.sources.map((s, i) => (
              <span key={i} className="px-2 py-0.5 rounded-md text-[10px] bg-[var(--color-bg-tertiary)] text-[var(--color-text-secondary)]">
                {s}
              </span>
            ))}
          </div>
        ) : null}
        {cm?.notes && <p className="text-xs text-[var(--color-text-muted)] italic">{cm.notes}</p>}
      </Block>

      {/* Block E: 个性化计划 */}
      <Block title="个性化计划" icon={Target}>
        {pp?.cv_changes?.length ? (
          <div className="space-y-2">
            {pp.cv_changes.map((c, i) => (
              <div key={i} className="text-xs space-y-0.5">
                <div className="font-medium text-[var(--color-text)]">{c.section}</div>
                <div className="text-[var(--color-text-muted)]">现状：{c.current || "—"}</div>
                <div className="text-success/80">建议：{c.proposed || "—"}</div>
                {c.why && <div className="text-[var(--color-text-muted)]">为什么：{c.why}</div>}
              </div>
            ))}
          </div>
        ) : (
          <p className="text-xs text-[var(--color-text-muted)]">无个性化计划数据</p>
        )}
        {pp?.linkedin_changes?.length ? (
          <div className="pt-1">
            <div className="text-[11px] font-medium text-[var(--color-text-muted)] mb-1">LinkedIn</div>
            {pp.linkedin_changes.map((l, i) => (
              <div key={i} className="text-xs text-[var(--color-text-secondary)]">· {l}</div>
            ))}
          </div>
        ) : null}
      </Block>

      {/* Block F: 面试故事映射 */}
      <Block title="面试故事映射" icon={MessagesSquare}>
        {stories.length ? (
          <div className="space-y-2">
            {stories.map((st, i) => (
              <div key={i} className="rounded-action bg-[var(--color-bg-secondary)] p-2.5 text-xs space-y-1">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium text-[var(--color-text)]">{st.story_title || `故事 ${i + 1}`}</span>
                  <span className="text-[var(--color-text-muted)] shrink-0 text-[10px]">{st.jd_requirement}</span>
                </div>
                {st.s && <div><span className="text-[var(--color-text-muted)]">S </span>{st.s}</div>}
                {st.t && <div><span className="text-[var(--color-text-muted)]">T </span>{st.t}</div>}
                {st.a && <div><span className="text-[var(--color-text-muted)]">A </span>{st.a}</div>}
                {st.r && <div><span className="text-[var(--color-text-muted)]">R </span>{st.r}</div>}
                {st.reflection && <div className="text-success/80">反思：{st.reflection}</div>}
              </div>
            ))}
          </div>
        ) : (
          <p className="text-xs text-[var(--color-text-muted)]">无面试故事数据</p>
        )}
      </Block>

      {/* Block G: 岗位可信度防坑 */}
      {cred && (
        <Block title="Block G · 岗位可信度防坑" icon={ShieldAlert} defaultOpen={cred.tier === "suspicious"}>
          <div className="flex items-center gap-2">
            <span
              className={`px-2 py-0.5 rounded-full text-[11px] font-medium border ${
                CRED_TIER_META[cred.tier ?? ""]?.cls ?? "text-[var(--color-text-muted)] bg-[var(--color-bg-secondary)] border-[var(--color-border)]"
              }`}
            >
              {CRED_TIER_META[cred.tier ?? ""]?.icon ?? "⚪"} {CRED_TIER_META[cred.tier ?? ""]?.label ?? cred.tier ?? "未知"}
            </span>
            <span className="text-[11px] text-[var(--color-text-muted)]">观察而非指控，每个信号都有合理解释</span>
          </div>
          {cred.signals?.length ? (
            <div className="space-y-1.5">
              {cred.signals.map((s, i) => (
                <div key={i} className="flex items-start gap-2 text-xs">
                  <span
                    className={`shrink-0 px-1.5 py-0.5 rounded-full text-[10px] font-medium ${
                      s.risk === "high"
                        ? "bg-danger/10 text-danger"
                        : s.risk === "medium"
                          ? "bg-warning/10 text-warning"
                          : "bg-[var(--color-bg-tertiary)] text-[var(--color-text-muted)]"
                    }`}
                  >
                    {s.risk}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="text-[var(--color-text)]">{s.signal}</div>
                    {s.note && <div className="text-[var(--color-text-muted)]">{s.note}</div>}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-[var(--color-text-muted)]">无风险信号数据</p>
          )}
          {cred.conclusion && (
            <p className="text-xs text-[var(--color-text-secondary)] leading-relaxed">{cred.conclusion}</p>
          )}
        </Block>
      )}
    </div>
  );
}
