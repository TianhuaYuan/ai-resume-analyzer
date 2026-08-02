/**
 * ExamplesPage — 简历范文页（真实数据）。
 *
 * - 列表：market/samples 卡片网格，展示 title + position(目标岗位) + category
 * - 点卡片：弹详情（market/samples/{id} 拿 payload），展示 target_position + category
 * - 用此范文创建简历（需登录）：
 *     · 快速套用：createBuilderResume({filename, modules, style}) → 进入编辑器
 *     · AI 结合我的信息改写：建空壳 → askBuilderStream 参照范文重写 → 进入编辑器
 * - 合规：不展示范文原文（含个人信息），只展示 title/position/category/target_position
 */

import { useEffect, useState, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import {
  CaretRight,
  MagnifyingGlass,
  CaretLeft,
  X,
  Target,
  Spinner,
  Sparkle,
  FilePlus,
  LockSimple,
} from "@phosphor-icons/react";
import LandingNav from "../components/LandingNav";
import { useAuth } from "../context/AuthContext";
import {
  listSamples,
  getSample,
  type ResumeSample,
  type ResumeSampleDetail,
} from "../api/market";
import { createBuilderResume, askBuilderStream } from "../api/builder";

// ── 内容 Tab 栏（对齐 ContentSection） ──

const CONTENT_TABS = [
  { key: "templates", label: "简历模板", route: "/templates" },
  { key: "examples", label: "简历范文", route: "/examples" },
  { key: "tips", label: "求职攻略", route: "/tips" },
];

function formatDate(dateStr?: string): string {
  if (!dateStr) return "";
  const normalized = /[Z+]/.test(dateStr) ? dateStr : dateStr + "Z";
  const d = new Date(normalized);
  if (isNaN(d.getTime())) return dateStr.slice(0, 10);
  return d.toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" });
}

// ── 范文详情弹窗 ──

interface SampleDetailModalProps {
  sample: ResumeSample | null;
  detail: ResumeSampleDetail | null;
  loading: boolean;
  busy: "quick" | "ai" | null;
  error: string;
  userLoggedIn: boolean;
  onQuickApply: () => void;
  onAiRewrite: () => void;
  onLogin: () => void;
  onClose: () => void;
}

function SampleDetailModal({
  sample,
  detail,
  loading,
  busy,
  error,
  userLoggedIn,
  onQuickApply,
  onAiRewrite,
  onLogin,
  onClose,
}: SampleDetailModalProps) {
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [onClose]);

  // 没有选中范文时不渲染（否则弹窗常驻无法关闭）
  if (!sample) return null;

  const modules = detail?.payload?.modules;
  const canQuickApply = !!modules && modules.length > 0;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-md glass-card shadow-2xl animate-fade-in-up">
        <div className="flex items-start justify-between gap-3 px-5 py-4 border-b border-[var(--color-border)]">
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-[var(--color-text)] leading-snug">
              {sample?.title ?? "范文详情"}
            </h3>
            <p className="text-[10px] text-[var(--color-text-muted)] mt-1">
              创建于 {formatDate(sample?.created_at)}
            </p>
          </div>
          <button onClick={onClose} className="p-1 rounded-lg text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-secondary)] transition-colors cursor-pointer shrink-0">
            <X size={16} weight="bold" />
          </button>
        </div>

        {loading || !detail ? (
          <div className="flex items-center justify-center py-16">
            <Spinner size={20} className="animate-spin text-[var(--color-text-muted)]" />
          </div>
        ) : (
          <>
            {/* 信息区（不展示范文原文） */}
            <div className="px-5 py-4 space-y-3">
              <div className="flex flex-wrap gap-1.5">
                {detail.position && (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-medium bg-brand/10 text-brand border border-brand/20">
                    <Target size={11} weight="duotone" /> 目标岗位：{detail.position}
                  </span>
                )}
                {detail.category && (
                  <span className="inline-flex px-2 py-0.5 rounded text-[10px] font-medium bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)] border border-[var(--color-border)]">
                    {detail.category}
                  </span>
                )}
              </div>
              {detail.payload?.target_position && detail.payload.target_position !== detail.position && (
                <p className="text-xs text-[var(--color-text-secondary)]">
                  适配岗位：{detail.payload.target_position}
                </p>
              )}
              <p className="text-[10px] text-[var(--color-text-muted)] leading-relaxed">
                范文原文（含个人信息）不对外展示，仅作为创建简历的结构参考。
              </p>
            </div>

            {/* 创建操作区 */}
            <div className="px-5 py-4 border-t border-[var(--color-border)]">
              <p className="text-xs font-medium text-[var(--color-text-secondary)] mb-2.5">
                用此范文创建简历
              </p>
              {userLoggedIn ? (
                <div className="space-y-2">
                  {canQuickApply && (
                    <button onClick={onQuickApply} disabled={busy !== null}
                      className="w-full flex items-center justify-center gap-1.5 px-4 py-2 rounded-full bg-brand text-white text-xs font-medium hover:bg-[#0077ed] hover:scale-[1.02] active:scale-[0.98] transition-all duration-300 cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed">
                      {busy === "quick" ? (
                        <Spinner size={13} className="animate-spin" />
                      ) : (
                        <FilePlus size={13} weight="bold" />
                      )}
                      {busy === "quick" ? "正在创建..." : "快速套用范文结构"}
                    </button>
                  )}
                  <button onClick={onAiRewrite} disabled={busy !== null}
                    className="w-full flex items-center justify-center gap-1.5 px-4 py-2 rounded-full bg-brand/10 text-brand border border-brand/30 text-xs font-medium hover:bg-brand/15 hover:scale-[1.02] active:scale-[0.98] transition-all duration-300 cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed">
                    {busy === "ai" ? (
                      <Spinner size={13} className="animate-spin" />
                    ) : (
                      <Sparkle size={13} weight="fill" />
                    )}
                    {busy === "ai" ? "AI 正在结合你的信息改写..." : "AI 结合我的信息改写"}
                  </button>
                  {!canQuickApply && (
                    <p className="text-[10px] text-[var(--color-text-muted)]">
                      该范文暂未生成结构数据，仅支持 AI 改写路径
                    </p>
                  )}
                  {error && (
                    <p className="text-xs text-red-500">{error}</p>
                  )}
                </div>
              ) : (
                <div className="flex items-center justify-between gap-3">
                  <p className="inline-flex items-center gap-1 text-xs text-[var(--color-text-muted)]">
                    <LockSimple size={12} /> 登录后使用此范文创建简历
                  </p>
                  <button onClick={onLogin}
                    className="px-4 py-1.5 rounded-full bg-brand text-white text-xs font-medium hover:bg-[#0077ed] hover:scale-[1.02] active:scale-[0.98] transition-all duration-300 cursor-pointer shrink-0">
                    登录
                  </button>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ── 主组件 ──

export default function ExamplesPage() {
  const navigate = useNavigate();
  const { user } = useAuth();

  const [samples, setSamples] = useState<ResumeSample[]>([]);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 详情弹窗
  const [selected, setSelected] = useState<ResumeSample | null>(null);
  const [detail, setDetail] = useState<ResumeSampleDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [busy, setBusy] = useState<"quick" | "ai" | null>(null);
  const [actionError, setActionError] = useState("");

  const handleQueryChange = useCallback((val: string) => {
    setQuery(val);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => { setDebouncedQuery(val); setPage(1); }, 300);
  }, []);

  // 加载范文列表
  useEffect(() => {
    setLoading(true);
    const filters: { q?: string; page: number; limit: number } = { page, limit: 12 };
    if (debouncedQuery) filters.q = debouncedQuery;
    listSamples(filters)
      .then((data) => { setSamples(data.items); setTotal(data.total); setTotalPages(data.total_pages); })
      .catch(() => { setSamples([]); setTotal(0); setTotalPages(0); })
      .finally(() => setLoading(false));
  }, [debouncedQuery, page]);

  // 打开详情 → 拉取范文详情（拿 payload）
  useEffect(() => {
    if (!selected) { setDetail(null); return; }
    setDetailLoading(true);
    setDetail(null);
    setActionError("");
    getSample(selected.id)
      .then(setDetail)
      .catch(() => setDetail(null))
      .finally(() => setDetailLoading(false));
  }, [selected]);

  const openSample = (sample: ResumeSample) => setSelected(sample);
  const closeSample = () => { setSelected(null); setDetail(null); };

  // 快速套用：直接带 modules/style 创建
  const handleQuickApply = async () => {
    if (!selected || !detail?.payload?.modules?.length) return;
    setActionError("");
    setBusy("quick");
    try {
      const resume = await createBuilderResume({
        filename: detail.title,
        modules: detail.payload.modules,
        style: detail.payload.style ?? null,
      });
      navigate(`/resumes/${resume.id}/edit`);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "创建失败，请重试");
      setBusy(null);
    }
  };

  // AI 改写：建空壳 → SSE 参照范文重写 → 完成后进入编辑器
  const handleAiRewrite = async () => {
    if (!selected) return;
    setActionError("");
    setBusy("ai");
    try {
      const resume = await createBuilderResume({ filename: selected.title });
      askBuilderStream(
        resume.id,
        `请参照范文《${selected.title}》的结构与风格，结合我的信息重写整份简历`,
        (evt) => {
          // 流完成后（agent_done）进入编辑器查看改写结果
          if (evt.type === "agent_done") {
            navigate(`/resumes/${resume.id}/edit`);
          }
        },
        (err) => {
          setBusy(null);
          setActionError(err.message || "AI 改写失败，请重试");
        },
        // 兜底：流非正常结束时复位忙碌态（不跳转，让用户重试）
        () => setBusy((prev) => (prev === "ai" ? null : prev)),
      );
    } catch (err) {
      setBusy(null);
      setActionError(err instanceof Error ? err.message : "创建失败，请重试");
    }
  };

  return (
    <div className="min-h-screen bg-[var(--color-bg)]">
      <LandingNav activeKey="examples" />

      <div className="max-w-7xl mx-auto px-6 py-8">
        {/* 内容 Tab 栏 */}
        <div className="flex items-center gap-1 mb-6 border-b border-[var(--color-border)]">
          {CONTENT_TABS.map((t) => (
            <button key={t.key} onClick={() => navigate(t.route)}
              className={`px-5 py-2.5 text-sm font-medium transition-all duration-300 cursor-pointer border-b-2 -mb-px
                ${t.key === "examples"
                  ? "text-brand border-brand"
                  : "text-[var(--color-text-muted)] border-transparent hover:text-[var(--color-text-secondary)]"
                }`}>
              {t.label}
            </button>
          ))}
        </div>

        {/* 搜索 + 统计 */}
        <div className="flex items-center gap-3 mb-6">
          <div className="relative flex-1 max-w-md">
            <MagnifyingGlass size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-text-muted)]" />
            <input type="text" value={query} onChange={(e) => handleQueryChange(e.target.value)}
              placeholder="搜索范文标题、目标岗位..."
              className="w-full pl-9 pr-3 py-2 rounded-xl bg-[#F2F2F7] border border-transparent
                text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:outline-none focus:bg-white focus:border-brand/40 focus:ring-4 focus:ring-brand/15 transition-colors" />
          </div>
          <span className="text-xs text-[var(--color-text-muted)] tabular-nums shrink-0">
            {loading ? "加载中..." : `共 ${total.toLocaleString()} 篇范文`}
          </span>
        </div>

        {/* 范文卡片网格 */}
        {loading ? (
          <div className="flex items-center justify-center py-24">
            <Spinner size={20} className="animate-spin text-[var(--color-text-muted)]" />
          </div>
        ) : samples.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-24">
            <Target size={32} className="text-[var(--color-text-muted)] mb-3" />
            <p className="text-sm text-[var(--color-text-secondary)]">数据同步中，请稍后再试</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
            {samples.map((s) => (
              <button key={s.id} onClick={() => openSample(s)}
                className="glass-card p-5 text-left hover:-translate-y-1 hover:shadow-xl hover:shadow-black/5 transition-all duration-300 cursor-pointer animate-fade-in-up group">
                <div className="flex items-start justify-between gap-2 mb-3">
                  <h3 className="text-sm font-semibold text-[var(--color-text)] leading-snug line-clamp-2 flex-1 min-w-0">
                    {s.title}
                  </h3>
                  <CaretRight size={14} className="shrink-0 text-[var(--color-text-muted)] group-hover:text-brand group-hover:translate-x-0.5 transition-all mt-0.5" />
                </div>
                <div className="flex items-center gap-1.5 flex-wrap">
                  {s.position && (
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-brand/10 text-brand border border-brand/20">
                      <Target size={10} weight="duotone" /> {s.position}
                    </span>
                  )}
                  {s.category && (
                    <span className="inline-flex px-2 py-0.5 rounded text-[10px] font-medium bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)] border border-[var(--color-border)]">
                      {s.category}
                    </span>
                  )}
                </div>
                {s.created_at && (
                  <p className="text-[10px] text-[var(--color-text-muted)] mt-3">{formatDate(s.created_at)}</p>
                )}
              </button>
            ))}
          </div>
        )}

        {/* 分页 */}
        {!loading && totalPages > 1 && (
          <div className="flex items-center justify-between mt-6">
            <span className="text-xs text-[var(--color-text-muted)]">第 {page}/{totalPages} 页，共 {total.toLocaleString()} 篇</span>
            <div className="flex items-center gap-2">
              <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1}
                className="p-2 rounded-full bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)] hover:bg-[#E5E5EA] disabled:opacity-30 disabled:cursor-not-allowed transition-all cursor-pointer">
                <CaretLeft size={14} weight="bold" />
              </button>
              {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                const start = Math.max(1, Math.min(page - 2, totalPages - 4));
                const p = start + i;
                if (p > totalPages) return null;
                return (
                  <button key={p} onClick={() => setPage(p)}
                    className={`w-8 h-8 rounded-full text-xs font-medium transition-all cursor-pointer
                      ${p === page ? "bg-brand/10 text-brand border border-brand/30" : "bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)] hover:bg-[#E5E5EA]"}`}>
                    {p}
                  </button>
                );
              })}
              <button onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page >= totalPages}
                className="p-2 rounded-full bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)] hover:bg-[#E5E5EA] disabled:opacity-30 disabled:cursor-not-allowed transition-all cursor-pointer">
                <CaretRight size={14} weight="bold" />
              </button>
            </div>
          </div>
        )}
      </div>

      {/* 范文详情弹窗 */}
      <SampleDetailModal
        sample={selected}
        detail={detail}
        loading={detailLoading}
        busy={busy}
        error={actionError}
        userLoggedIn={!!user}
        onQuickApply={handleQuickApply}
        onAiRewrite={handleAiRewrite}
        onLogin={() => window.dispatchEvent(new CustomEvent("open-login-modal"))}
        onClose={closeSample}
      />
    </div>
  );
}
