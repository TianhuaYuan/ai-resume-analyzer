/**
 * PendingChangesDialog — 待审阅改动弹窗（E2 核心交互）。
 *
 * 改写类工具（rewrite_star/translate/rewrite_resume）落库时后端会写入
 * pending_changes（字段级 diff：before/after/rationale）。本弹窗让用户
 * 在 Builder 编辑页逐条「接受 / 拒绝」，或「全部清除」。
 *
 * 接受/拒绝只是确认 AI 改动是否保留，真正固化需要用户保存简历——
 * 因此操作后弹窗内会提示「请保存简历以固化改动」。
 *
 * 数据接口（api/pendingChanges.ts，user_id 隔离）：
 *   - listPendingChanges / acceptPendingChange / rejectPendingChange / clearPendingChanges
 *
 * 风格：原生 <dialog> + Esc 关闭，对齐 VersionHistoryDialog / ConfirmDialog。
 */

import { useEffect, useRef, useState, useCallback } from "react";
import {
  X,
  Check,
  Prohibit,
  Trash,
  ClipboardText,
  ArrowClockwise,
} from "@phosphor-icons/react";
import {
  listPendingChanges,
  acceptPendingChange,
  rejectPendingChange,
  clearPendingChanges,
  type PendingChange,
} from "../api/pendingChanges";

interface PendingChangesDialogProps {
  resumeId: number;
  open: boolean;
  onClose: () => void;
  /** 操作（接受/拒绝/清空）发生后通知父组件刷新入口徽标 */
  onChanged?: () => void;
}

/** 工具名中文映射（改写类工具为主，兜底原文） */
const TOOL_LABELS: Record<string, string> = {
  rewrite_star: "STAR 改写",
  translate: "翻译",
  rewrite_resume: "重写简历",
  generate_module: "生成模块",
  modify_module: "修改模块",
};

function toolLabel(name: string): string {
  return TOOL_LABELS[name] ?? name;
}

/** 字段值展示：对象/数组转 JSON，字符串原样，空值占位 */
function formatValue(v: unknown): string {
  if (v === null || v === undefined) return "（空）";
  if (typeof v === "string") return v;
  if (typeof v === "object") {
    try {
      return JSON.stringify(v, null, 2);
    } catch {
      return String(v);
    }
  }
  return String(v);
}

type Status = "loading" | "error" | "success";
type NoticeType = "info" | "success" | "danger";

export default function PendingChangesDialog({
  resumeId,
  open,
  onClose,
  onChanged,
}: PendingChangesDialogProps) {
  const [status, setStatus] = useState<Status>("loading");
  const [items, setItems] = useState<PendingChange[]>([]);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);
  const [clearing, setClearing] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [noticeType, setNoticeType] = useState<NoticeType>("info");
  const cancelledRef = useRef(false);
  const dialogRef = useRef<HTMLDialogElement>(null);

  const showNotice = useCallback((msg: string, type: NoticeType = "info") => {
    setNotice(msg);
    setNoticeType(type);
  }, []);

  const load = useCallback(async () => {
    cancelledRef.current = false;
    setStatus("loading");
    setError("");
    try {
      const res = await listPendingChanges(resumeId);
      if (cancelledRef.current) return;
      setItems(res.items ?? []);
      setStatus("success");
      setConfirmClear(false);
    } catch (err: unknown) {
      if (cancelledRef.current) return;
      setError(err instanceof Error ? err.message : "加载待审阅改动失败");
      setStatus("error");
    }
  }, [resumeId]);

  useEffect(() => {
    if (!open) return;
    setNotice(null);
    setConfirmClear(false);
    load();
    return () => {
      cancelledRef.current = true;
    };
  }, [open, load]);

  // 原生 <dialog>，showModal/close 控制，Esc 原生支持
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open) {
      try {
        dialog.showModal();
      } catch {
        dialog.open = true;
      }
    } else {
      try {
        dialog.close();
      } catch {
        dialog.open = false;
      }
    }
  }, [open]);

  const handleRetry = () => load();

  const handleCancel = (e: React.FormEvent<HTMLDialogElement>) => {
    e.preventDefault();
    onClose();
  };

  const handleAccept = async (c: PendingChange) => {
    setBusyId(c.id);
    try {
      await acceptPendingChange(resumeId, c.id);
      setItems((prev) => prev.filter((i) => i.id !== c.id));
      showNotice(`已接受「${toolLabel(c.tool_name)}」的改动，请保存简历以固化`, "success");
      onChanged?.();
    } catch (err: unknown) {
      showNotice(err instanceof Error ? err.message : "接受失败，请重试", "danger");
    } finally {
      setBusyId(null);
    }
  };

  const handleReject = async (c: PendingChange) => {
    setBusyId(c.id);
    try {
      await rejectPendingChange(resumeId, c.id);
      setItems((prev) => prev.filter((i) => i.id !== c.id));
      showNotice(`已拒绝「${toolLabel(c.tool_name)}」的改动，请保存简历以固化`, "info");
      onChanged?.();
    } catch (err: unknown) {
      showNotice(err instanceof Error ? err.message : "拒绝失败，请重试", "danger");
    } finally {
      setBusyId(null);
    }
  };

  const handleClearAll = async () => {
    if (items.length === 0) return;
    setClearing(true);
    try {
      await clearPendingChanges(resumeId);
      setItems([]);
      setConfirmClear(false);
      showNotice("已清空全部待审阅改动", "success");
      onChanged?.();
    } catch (err: unknown) {
      showNotice(err instanceof Error ? err.message : "清空失败，请重试", "danger");
    } finally {
      setClearing(false);
    }
  };

  if (!open) return null;

  const noticeColor =
    noticeType === "success"
      ? "text-emerald-500 bg-emerald-500/10 border-emerald-500/20"
      : noticeType === "danger"
        ? "text-red-400 bg-red-500/10 border-red-500/20"
        : "text-sky-500 bg-sky-500/10 border-sky-500/20";

  return (
    <dialog
      ref={dialogRef}
      onCancel={handleCancel}
      onClose={handleCancel}
      className="fixed inset-0 z-50 m-0 w-full h-full p-0 overflow-hidden
        bg-black/60 backdrop-blur-sm motion-reduce:backdrop-blur-none"
      role="dialog"
      aria-modal="true"
      aria-label="待审阅改动"
    >
      <div
        className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2
          bg-[var(--color-surface)] border border-[var(--color-border)] rounded-2xl
          w-[calc(100vw-2rem)] sm:max-w-xl md:max-w-2xl
          shadow-2xl
          animate-fade-in-up motion-reduce:animate-none
          flex flex-col overflow-hidden
          max-h-[85dvh]"
      >
        {/* 头部 */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--color-border)] shrink-0">
          <div className="min-w-0 flex-1">
            <h3 className="text-base font-semibold text-[var(--color-text)]">
              待审阅改动
            </h3>
            <p className="text-xs text-[var(--color-text-muted)] mt-0.5">
              AI 改写/翻译的建议逐条确认，接受或拒绝后记得保存简历固化
              {status === "success" && (
                <span className="ml-1.5 text-[var(--color-text-secondary)]">
                  共{" "}
                  <span className="text-[var(--color-text)] font-medium tabular-nums">
                    {items.length}
                  </span>{" "}
                  条
                </span>
              )}
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label="关闭"
            className="ml-3 p-1.5 rounded-lg text-[var(--color-text-secondary)]
              hover:text-[var(--color-text)] hover:bg-[var(--color-bg-secondary)]
              active:scale-[0.95] motion-reduce:active:scale-100
              transition-all cursor-pointer shrink-0"
          >
            <X size={18} weight="bold" aria-hidden="true" />
          </button>
        </div>

        {/* 内容区 */}
        <div
          className="flex-1 overflow-y-auto px-6 py-5 space-y-3.5"
          style={{ scrollbarGutter: "stable" }}
        >
          {/* 内联提示（接受/拒绝/清空后的反馈，含保存引导） */}
          {notice && (
            <div
              className={`px-3.5 py-2.5 rounded-xl border text-xs leading-relaxed ${noticeColor}`}
              role="status"
            >
              {notice}
            </div>
          )}

          {status === "loading" && (
            <div className="space-y-3" aria-busy="true" aria-live="polite">
              <div className="h-16 rounded-lg animate-skeleton" />
              <div className="h-16 rounded-lg animate-skeleton" />
              <div className="h-16 rounded-lg animate-skeleton" />
            </div>
          )}

          {status === "error" && (
            <div
              className="p-4 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400"
              role="alert"
            >
              <p className="text-sm mb-3">{error}</p>
              <button
                onClick={handleRetry}
                className="inline-flex items-center gap-1.5 px-3 py-1.5
                  text-xs font-medium rounded-lg
                  bg-red-500/15 hover:bg-red-500/25
                  border border-red-500/30
                  text-red-300
                  active:scale-[0.98] motion-reduce:active:scale-100
                  transition-all cursor-pointer"
              >
                <ArrowClockwise size={14} weight="bold" aria-hidden="true" />
                重试
              </button>
            </div>
          )}

          {status === "success" && items.length === 0 && (
            <div className="text-center py-12 text-[var(--color-text-muted)] text-sm">
              <ClipboardText
                size={28}
                weight="duotone"
                className="mx-auto mb-3 opacity-60"
                aria-hidden="true"
              />
              暂无待审阅改动
              <p className="text-xs mt-1.5 opacity-80">
                AI 改写 / 翻译生成建议后会出现在这里，供你逐条确认
              </p>
            </div>
          )}

          {status === "success" && items.length > 0 && (
            <>
              {items.map((c) => {
                const busy = busyId === c.id;
                return (
                  <div
                    key={c.id}
                    className="border border-[var(--color-border)] rounded-xl overflow-hidden bg-white/[0.03]"
                  >
                    {/* 条目头：工具名 + 字段路径 */}
                    <div className="flex items-center gap-2 px-4 py-2.5 border-b border-[var(--color-border)] bg-white/[0.02]">
                      <span
                        className="inline-flex items-center px-1.5 py-0.5 rounded
                          text-[10px] font-medium bg-brand/15 text-brand border border-brand/25"
                      >
                        {toolLabel(c.tool_name)}
                      </span>
                      <span
                        className="min-w-0 flex-1 truncate font-mono text-[11px] text-[var(--color-text-secondary)]"
                        title={c.field_path}
                      >
                        {c.field_path}
                      </span>
                      <span
                        className="shrink-0 px-1.5 py-0.5 rounded text-[10px] font-medium
                          bg-[var(--color-bg-secondary)] text-[var(--color-text-muted)] border border-[var(--color-border)]"
                      >
                        待确认
                      </span>
                    </div>

                    {/* 改动对比：before / after */}
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 px-4 py-3">
                      <div className="min-w-0">
                        <p className="text-[10px] font-medium text-[var(--color-text-muted)] mb-1.5">
                          原文
                        </p>
                        <pre className="whitespace-pre-wrap break-words text-[11px] leading-relaxed text-red-400/90
                          bg-red-500/[0.06] border border-red-500/15 rounded-lg px-3 py-2
                          max-h-28 overflow-y-auto">
                          {formatValue(c.before)}
                        </pre>
                      </div>
                      <div className="min-w-0">
                        <p className="text-[10px] font-medium text-[var(--color-text-muted)] mb-1.5">
                          AI 建议
                        </p>
                        <pre className="whitespace-pre-wrap break-words text-[11px] leading-relaxed text-emerald-400/90
                          bg-emerald-500/[0.06] border border-emerald-500/15 rounded-lg px-3 py-2
                          max-h-28 overflow-y-auto">
                          {formatValue(c.after)}
                        </pre>
                      </div>
                    </div>

                    {/* rationale */}
                    {c.rationale ? (
                      <div className="px-4 pb-3">
                        <p className="text-[10px] font-medium text-[var(--color-text-muted)] mb-1">
                          理由
                        </p>
                        <p className="text-xs text-[var(--color-text-secondary)] leading-relaxed">
                          {c.rationale}
                        </p>
                      </div>
                    ) : null}

                    {/* 操作按钮 */}
                    <div className="flex items-center justify-end gap-2 px-4 py-2.5 border-t border-[var(--color-border)] bg-white/[0.02]">
                      <button
                        onClick={() => handleReject(c)}
                        disabled={busy || clearing}
                        className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg
                          text-xs font-medium text-[var(--color-text-secondary)]
                          bg-[var(--color-bg-secondary)] hover:bg-[#E5E5EA]
                          active:scale-[0.98] motion-reduce:active:scale-100
                          transition-all cursor-pointer
                          disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        <Prohibit size={13} weight="bold" aria-hidden="true" />
                        拒绝
                      </button>
                      <button
                        onClick={() => handleAccept(c)}
                        disabled={busy || clearing}
                        className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg
                          text-xs font-medium text-white bg-brand hover:bg-[#0077ed]
                          active:scale-[0.98] motion-reduce:active:scale-100
                          transition-all cursor-pointer
                          disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        {busy ? (
                          <span
                            className="inline-block w-3 h-3 rounded-full border-2
                              border-white border-t-transparent animate-spin"
                            aria-hidden="true"
                          />
                        ) : (
                          <Check size={13} weight="bold" aria-hidden="true" />
                        )}
                        接受
                      </button>
                    </div>
                  </div>
                );
              })}
            </>
          )}
        </div>

        {/* 底部：保存引导 + 全部清除 */}
        {status === "success" && (
          <div className="shrink-0 px-6 py-4 border-t border-[var(--color-border)]">
            <p className="text-[11px] text-[var(--color-text-muted)] mb-3">
              提示：接受/拒绝只是确认 AI 改动，点击编辑器右上角「完成」保存后才能固化。
            </p>
            {confirmClear ? (
              <div className="flex items-center justify-between gap-3 flex-wrap">
                <p className="text-xs text-red-400">
                  确定清除全部 {items.length} 条待审阅改动？此操作不可撤销。
                </p>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setConfirmClear(false)}
                    disabled={clearing}
                    className="px-3 py-1.5 rounded-lg text-xs font-medium
                      text-[var(--color-text-secondary)] bg-[var(--color-bg-secondary)]
                      hover:bg-[#E5E5EA] transition-all cursor-pointer
                      disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    取消
                  </button>
                  <button
                    onClick={() => void handleClearAll()}
                    disabled={clearing}
                    className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg
                      text-xs font-medium text-red-400
                      bg-red-500/15 border border-red-500/30 hover:bg-red-500/25
                      active:scale-[0.98] motion-reduce:active:scale-100
                      transition-all cursor-pointer
                      disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {clearing ? (
                      <span
                        className="inline-block w-3 h-3 rounded-full border-2
                          border-red-400 border-t-transparent animate-spin"
                        aria-hidden="true"
                      />
                    ) : (
                      <Trash size={13} weight="bold" aria-hidden="true" />
                    )}
                    确认清除
                  </button>
                </div>
              </div>
            ) : (
              <div className="flex items-center justify-end">
                <button
                  onClick={() => setConfirmClear(true)}
                  disabled={clearing || items.length === 0}
                  className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg
                    text-xs font-medium text-red-400
                    bg-red-500/10 border border-red-500/25 hover:bg-red-500/20
                    active:scale-[0.98] motion-reduce:active:scale-100
                    transition-all cursor-pointer
                    disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  <Trash size={13} weight="bold" aria-hidden="true" />
                  全部清除
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </dialog>
  );
}
