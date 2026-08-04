import { useCallback, useEffect, useState } from "react";
import {
  Plus,
  Spinner,
  Trash,
  PencilSimple,
  X,
  Books,
  Briefcase,
  ChatCircle,
  NotePencil,
  CaretLeft,
  CaretRight,
} from "@phosphor-icons/react";
import {
  listAssets,
  createAsset,
  updateAsset,
  deleteAsset,
  type KnowledgeAsset,
  type KnowledgeAssetType,
} from "../api/assets";
import { useToast } from "../components/Toast";
import ConfirmDialog from "../components/ConfirmDialog";

// ── 常量 ──

const PAGE_SIZE = 10;

/** 类型 Tab 配置 */
const TABS: Array<{ key: KnowledgeAssetType | "all"; label: string; icon: typeof Books }> = [
  { key: "all", label: "全部", icon: Books },
  { key: "jd", label: "JD", icon: Briefcase },
  { key: "interview", label: "面试记录", icon: ChatCircle },
  { key: "note", label: "笔记", icon: NotePencil },
];

/** 类型徽章配色 */
const TYPE_META: Record<KnowledgeAssetType, { label: string; color: string; bg: string }> = {
  jd: { label: "JD", color: "text-sky-600", bg: "bg-sky-500/15 border-sky-500/30" },
  interview: { label: "面试记录", color: "text-violet-500", bg: "bg-violet-500/15 border-violet-500/30" },
  note: { label: "笔记", color: "text-amber-600", bg: "bg-amber-500/15 border-amber-500/30" },
};

/** 新建/编辑表单状态 */
interface AssetFormState {
  asset_type: KnowledgeAssetType;
  title: string;
  content: string;
  is_draft: boolean;
}

const EMPTY_FORM: AssetFormState = { asset_type: "jd", title: "", content: "", is_draft: false };

/** ISO → "MM-DD HH:mm"（北京时间）。后端 naive datetime 视为 UTC。 */
function formatTimestamp(dateStr?: string): string {
  if (!dateStr) return "-";
  const normalized = /[Z+]/.test(dateStr) ? dateStr : dateStr + "Z";
  const d = new Date(normalized);
  if (isNaN(d.getTime())) return "-";
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(d);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  return `${get("month")}-${get("day")} ${get("hour")}:${get("minute")}`;
}

/**
 * 知识资产页面（A4）— 管理个人知识库。
 *
 * 功能：
 * - 类型筛选 Tab：全部 / JD / 面试记录 / 笔记
 * - 新建 / 编辑弹窗表单（标题 + 类型 + 内容 + 草稿开关）
 * - 列表项：标题、类型徽章、内容摘要（截断）、版本、索引状态徽章、创建时间
 * - 行操作：编辑（回填弹窗）、删除（ConfirmDialog 确认）
 * - 分页（total 超 limit 时）、空态、加载态
 */
export default function AssetsPage() {
  const toast = useToast();

  const [tab, setTab] = useState<KnowledgeAssetType | "all">("all");
  const [page, setPage] = useState(1);
  const [assets, setAssets] = useState<KnowledgeAsset[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);

  // 弹窗状态
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<KnowledgeAsset | null>(null);
  const [form, setForm] = useState<AssetFormState>(EMPTY_FORM);
  const [saving, setSaving] = useState(false);

  // 删除确认
  const [deleteTarget, setDeleteTarget] = useState<KnowledgeAsset | null>(null);
  const [deleting, setDeleting] = useState(false);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const fetchAssets = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listAssets({
        asset_type: tab === "all" ? undefined : tab,
        page,
        limit: PAGE_SIZE,
      });
      setAssets(data.items);
      setTotal(data.total);
    } catch {
      // 静默失败，不打断用户
    } finally {
      setLoading(false);
    }
  }, [tab, page]);

  useEffect(() => {
    void fetchAssets();
  }, [fetchAssets]);

  const handleTabChange = (key: KnowledgeAssetType | "all") => {
    setTab(key);
    setPage(1);
  };

  const openCreate = () => {
    setEditing(null);
    setForm(EMPTY_FORM);
    setModalOpen(true);
  };

  const openEdit = (a: KnowledgeAsset) => {
    setEditing(a);
    setForm({
      asset_type: a.asset_type,
      title: a.title,
      content: a.content,
      is_draft: a.is_draft,
    });
    setModalOpen(true);
  };

  const closeModal = () => {
    if (saving) return;
    setModalOpen(false);
    setEditing(null);
    setForm(EMPTY_FORM);
  };

  const handleSave = async () => {
    if (!form.title.trim() || !form.content.trim()) {
      toast.error("标题和内容不能为空");
      return;
    }
    setSaving(true);
    try {
      if (editing) {
        await updateAsset(editing.id, {
          title: form.title.trim(),
          content: form.content.trim(),
          is_draft: form.is_draft,
        });
        toast.success("已更新");
      } else {
        await createAsset({
          asset_type: form.asset_type,
          title: form.title.trim(),
          content: form.content.trim(),
          is_draft: form.is_draft,
        });
        toast.success("已创建");
        // 新资产落在列表最前，回到第 1 页查看
        setPage(1);
      }
      setModalOpen(false);
      setEditing(null);
      setForm(EMPTY_FORM);
      void fetchAssets();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await deleteAsset(deleteTarget.id);
      toast.success("已删除");
      // 当前页删空且非第一页 → 回退一页
      if (assets.length === 1 && page > 1) setPage(page - 1);
      else void fetchAssets();
    } catch {
      toast.error("删除失败");
    } finally {
      setDeleting(false);
      setDeleteTarget(null);
    }
  };

  const indexBadge = (a: KnowledgeAsset) =>
    a.indexed ? (
      <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium bg-emerald-500/15 text-emerald-600 border border-emerald-500/30">
        已索引
      </span>
    ) : (
      <span
        className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium bg-amber-500/15 text-amber-600 border border-amber-500/30"
        title="向量索引尚未就绪，更新后会自动重建"
      >
        待索引
      </span>
    );

  return (
    <>
      <div className="min-h-screen bg-[var(--color-bg)]">
        <div className="max-w-7xl mx-auto px-6 md:px-8 lg:px-12 py-8">
          {/* ── 标题区 ── */}
          <header className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-8">
            <div>
              <h1 className="text-2xl font-bold text-[var(--color-text)]">知识资产</h1>
              <p className="text-sm text-[var(--color-text-secondary)] mt-1">
                沉淀 JD、面试记录与笔记，构建你的个人知识库
              </p>
            </div>

            <button
              onClick={openCreate}
              className="inline-flex items-center justify-center gap-1.5 px-3.5 py-2 rounded-full
                text-sm font-medium text-white
                bg-brand
                hover:bg-[#0077ed] hover:scale-[1.02] hover:shadow-lg hover:shadow-brand/25
                active:scale-[0.98] motion-reduce:active:scale-100
                transition-all duration-300 cursor-pointer"
              aria-label="新建知识资产"
            >
              <Plus size={14} weight="bold" aria-hidden="true" />
              新建资产
            </button>
          </header>

          {/* ── 类型筛选 Tab ── */}
          <div className="flex items-center gap-1 mb-6 border-b border-[var(--color-border)]">
            {TABS.map((t) => {
              const Icon = t.icon;
              const active = tab === t.key;
              return (
                <button
                  key={t.key}
                  onClick={() => handleTabChange(t.key)}
                  className={`inline-flex items-center gap-1.5 px-4 py-2.5 text-xs font-medium transition-all cursor-pointer border-b-2 -mb-px
                    ${active
                      ? "text-brand border-brand"
                      : "text-[var(--color-text-muted)] border-transparent hover:text-[var(--color-text-secondary)]"
                    }`}
                  aria-selected={active}
                  role="tab"
                >
                  <Icon size={13} weight={active ? "fill" : "regular"} aria-hidden="true" />
                  {t.label}
                </button>
              );
            })}
          </div>

          {/* ── 结果统计 ── */}
          <div className="flex items-center justify-between mb-4">
            <span className="text-xs text-[var(--color-text-muted)] tabular-nums">
              {loading ? "加载中..." : `${total.toLocaleString()} 条资产`}
            </span>
          </div>

          {/* ── 列表 ── */}
          {loading ? (
            <div className="flex items-center justify-center py-32">
              <Spinner
                size={24}
                className="animate-spin text-[var(--color-text-muted)] mr-2"
                aria-hidden="true"
              />
              <span className="text-sm text-[var(--color-text-secondary)]">加载中...</span>
            </div>
          ) : assets.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-32 text-center">
              <Books
                size={48}
                weight="duotone"
                className="text-[var(--color-text-muted)] mb-4"
                aria-hidden="true"
              />
              <p className="text-base text-[var(--color-text-secondary)]">还没有知识资产</p>
              <p className="text-sm text-[var(--color-text-muted)] mt-1.5">
                点击「新建资产」，沉淀一条 JD、面试记录或笔记
              </p>
            </div>
          ) : (
            <div className="flex flex-col gap-4">
              {assets.map((a) => {
                const meta = TYPE_META[a.asset_type];
                return (
                  <div
                    key={a.id}
                    className="group rounded-2xl bg-white/80 backdrop-blur-xl border border-[var(--color-border)]
                      p-4 hover:border-brand/40 hover:shadow-lg hover:shadow-black/5
                      transition-all duration-300"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span
                            className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium ${meta.color} ${meta.bg}`}
                          >
                            {meta.label}
                          </span>
                          {a.is_draft && (
                            <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium bg-zinc-500/15 text-zinc-500 border border-zinc-500/30">
                              草稿
                            </span>
                          )}
                        </div>
                        <h3
                          className="text-sm font-medium text-[var(--color-text)] mt-2 truncate"
                          title={a.title}
                        >
                          {a.title}
                        </h3>
                        <p className="text-xs text-[var(--color-text-secondary)] mt-1 line-clamp-2 leading-relaxed break-words">
                          {a.content}
                        </p>
                      </div>

                      {/* 行操作 */}
                      <div className="flex items-center gap-1 shrink-0">
                        <button
                          onClick={() => openEdit(a)}
                          className="p-1.5 rounded-md text-[var(--color-text-muted)] hover:text-sky-400 hover:bg-sky-500/10 transition-all cursor-pointer"
                          aria-label={`编辑 ${a.title}`}
                          title="编辑"
                        >
                          <PencilSimple size={14} weight="bold" aria-hidden="true" />
                        </button>
                        <button
                          onClick={() => setDeleteTarget(a)}
                          className="p-1.5 rounded-md text-[var(--color-text-muted)] hover:text-red-400 hover:bg-red-500/10 transition-all cursor-pointer"
                          aria-label={`删除 ${a.title}`}
                          title="删除"
                        >
                          <Trash size={14} weight="bold" aria-hidden="true" />
                        </button>
                      </div>
                    </div>

                    {/* 元信息 */}
                    <div className="flex flex-wrap items-center gap-3 mt-3 pt-3 border-t border-[var(--color-border)]">
                      {indexBadge(a)}
                      <span className="text-[10px] text-[var(--color-text-muted)] tabular-nums">
                        v{a.version}
                      </span>
                      <span className="text-[10px] text-[var(--color-text-muted)]">
                        创建于 {formatTimestamp(a.created_at)}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {/* ── 分页 ── */}
          {!loading && totalPages > 1 && (
            <div className="flex items-center justify-between mt-6">
              <span className="text-xs text-[var(--color-text-muted)]">
                第 {page}/{totalPages} 页，共 {total.toLocaleString()} 条
              </span>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page <= 1}
                  className="p-2 rounded-full bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)] hover:bg-[#E5E5EA] disabled:opacity-30 disabled:cursor-not-allowed transition-all cursor-pointer"
                  aria-label="上一页"
                >
                  <CaretLeft size={14} weight="bold" aria-hidden="true" />
                </button>
                {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                  const start = Math.max(1, Math.min(page - 2, totalPages - 4));
                  const p = start + i;
                  if (p > totalPages) return null;
                  return (
                    <button
                      key={p}
                      onClick={() => setPage(p)}
                      className={`w-8 h-8 rounded-full text-xs font-medium transition-all cursor-pointer
                        ${p === page
                          ? "bg-brand/10 text-brand border border-brand/30"
                          : "bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)] hover:bg-[#E5E5EA]"
                        }`}
                      aria-label={`第 ${p} 页`}
                    >
                      {p}
                    </button>
                  );
                })}
                <button
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page >= totalPages}
                  className="p-2 rounded-full bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)] hover:bg-[#E5E5EA] disabled:opacity-30 disabled:cursor-not-allowed transition-all cursor-pointer"
                  aria-label="下一页"
                >
                  <CaretRight size={14} weight="bold" aria-hidden="true" />
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── 新建 / 编辑弹窗 ── */}
      {modalOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm"
          onClick={closeModal}
          role="dialog"
          aria-modal="true"
          aria-label={editing ? "编辑知识资产" : "新建知识资产"}
        >
          <div
            className="w-full max-w-lg rounded-2xl bg-[var(--color-bg)] border border-[var(--color-border)] p-5 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-4">
              <div className="min-w-0">
                <h3 className="text-base font-semibold text-[var(--color-text)]">
                  {editing ? "编辑知识资产" : "新建知识资产"}
                </h3>
                <p className="text-xs text-[var(--color-text-muted)] mt-0.5">
                  支持 JD / 面试记录 / 笔记，自动进入知识库索引
                </p>
              </div>
              <button
                onClick={closeModal}
                disabled={saving}
                className="p-1.5 rounded-md text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-secondary)] transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                aria-label="关闭"
              >
                <X size={16} weight="bold" aria-hidden="true" />
              </button>
            </div>

            {/* 类型选择 */}
            <div className="mb-4">
              <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">
                类型
              </label>
              <div className="flex flex-wrap items-center gap-2">
                {(["jd", "interview", "note"] as KnowledgeAssetType[]).map((t) => {
                  const active = form.asset_type === t;
                  const meta = TYPE_META[t];
                  return (
                    <button
                      key={t}
                      type="button"
                      onClick={() => setForm((f) => ({ ...f, asset_type: t }))}
                      className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition-all cursor-pointer
                        ${active
                          ? `${meta.color} ${meta.bg}`
                          : "bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)] hover:bg-[#E5E5EA] border border-transparent"
                        }`}
                      aria-pressed={active}
                    >
                      {meta.label}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* 标题 */}
            <div className="mb-4">
              <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">
                标题
              </label>
              <input
                type="text"
                value={form.title}
                onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
                placeholder="输入标题，如「字节后端一面」"
                maxLength={200}
                className="w-full px-3 py-2.5 rounded-xl text-sm bg-[var(--color-bg-secondary)] border border-[var(--color-border)] text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] outline-none focus:border-brand/50 focus:ring-4 focus:ring-brand/15 transition-all"
              />
            </div>

            {/* 内容 */}
            <div className="mb-4">
              <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">
                内容
              </label>
              <textarea
                value={form.content}
                onChange={(e) => setForm((f) => ({ ...f, content: e.target.value }))}
                placeholder="粘贴 JD 文本、面试复盘或学习笔记..."
                rows={8}
                className="w-full px-3 py-2.5 rounded-xl text-sm bg-[var(--color-bg-secondary)] border border-[var(--color-border)] text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] outline-none focus:border-brand/50 focus:ring-4 focus:ring-brand/15 transition-all resize-none"
              />
            </div>

            {/* 草稿开关 */}
            <div className="flex items-center justify-between mb-5">
              <span className="text-xs font-medium text-[var(--color-text-secondary)]">
                保存为草稿
              </span>
              <button
                type="button"
                onClick={() => setForm((f) => ({ ...f, is_draft: !f.is_draft }))}
                className={`w-9 h-5 rounded-full transition-colors relative cursor-pointer
                  ${form.is_draft ? "bg-brand" : "bg-[var(--color-bg-secondary)] border border-[var(--color-border)]"}`}
                aria-label="保存为草稿"
                aria-pressed={form.is_draft}
              >
                <span
                  className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform
                    ${form.is_draft ? "translate-x-4" : ""}`}
                />
              </button>
            </div>

            <div className="flex items-center justify-end gap-2">
              <button
                onClick={closeModal}
                disabled={saving}
                className="px-3.5 py-2 rounded-lg text-sm font-medium text-[var(--color-text-secondary)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-secondary)] active:scale-[0.98] transition-all cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
              >
                取消
              </button>
              <button
                onClick={() => void handleSave()}
                disabled={saving}
                className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-sm font-medium text-white bg-brand hover:bg-[#0077ed] active:scale-[0.98] transition-all cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {saving && (
                  <Spinner size={14} className="animate-spin" aria-hidden="true" />
                )}
                {editing ? "保存修改" : "创建"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── 删除确认弹窗 ── */}
      <ConfirmDialog
        open={deleteTarget !== null}
        title="确认删除"
        description={`确定删除「${deleteTarget?.title ?? ""}」吗？此操作不可撤销。`}
        confirmText="删除"
        danger
        loading={deleting}
        onConfirm={() => void handleDelete()}
        onCancel={() => setDeleteTarget(null)}
      />
    </>
  );
}
