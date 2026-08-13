import { useEffect, useState } from "react";
import { Check, CheckCheck, LoaderCircle, TriangleAlert, X } from "lucide-react";
import { listResumes, type ResumeItem } from "../api/resumes";

interface CompareSelectDialogProps {
  open: boolean;
  currentResumeId: number; // 当前简历 ID，固定作为对比基准
  onConfirm: (selectedIds: number[]) => void;
  onCancel: () => void;
}

const MIN_SELECT = 1;
const MAX_SELECT = 5;

/**
 * 简历对比选择弹窗。
 *
 * 用途：当前简历固定作为基准，再从列表中勾选 1-5 份其他简历。
 *
 * - 打开时拉取 listResumes()，仅展示 status === "ready" 且非当前简历的项
 * - 选满 MAX_SELECT 后禁止继续勾选，未选项降透明度提示
 * - 至少选 MIN_SELECT 份才可确认
 * - 关闭方式：Esc / 点 backdrop / 点 X / 点取消
 */
export function CompareSelectDialog({
  open,
  currentResumeId,
  onConfirm,
  onCancel,
}: CompareSelectDialogProps) {
  const [resumes, setResumes] = useState<ResumeItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [selectedIds, setSelectedIds] = useState<number[]>([]);

  // 打开时拉取简历列表并重置选择
  useEffect(() => {
    if (!open) return;

    setLoading(true);
    setError("");
    setSelectedIds([]);

    listResumes(50)
      .then((data) => {
        // 当前简历由调用方固定加入请求；这里只展示其他已完成简历。
        const filtered = data.items.filter(
          (r) => r.id !== currentResumeId && r.status === "ready",
        );
        setResumes(filtered);
        setLoading(false);
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "加载简历列表失败");
        setLoading(false);
      });
  }, [open, currentResumeId]);

  // Esc 关闭
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onCancel]);

  if (!open) return null;

  const toggle = (id: number) => {
    setSelectedIds((prev) => {
      if (prev.includes(id)) return prev.filter((x) => x !== id);
      if (prev.length >= MAX_SELECT) return prev; // 选满禁止继续选
      return [...prev, id];
    });
  };

  const isFull = selectedIds.length >= MAX_SELECT;
  const canConfirm = selectedIds.length >= MIN_SELECT;

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/60 backdrop-blur-sm motion-reduce:backdrop-blur-none p-2 sm:p-4"
      role="dialog"
      aria-modal="true"
      aria-label="选择对比简历"
      onClick={onCancel}
    >
      <div
        className="modal-mobile-sheet relative w-full max-w-md mx-0 sm:mx-4 p-6 rounded-input glass-card shadow-2xl max-h-[calc(100dvh-1rem)] sm:max-h-[85vh] overflow-y-auto animate-fade-in-up motion-reduce:animate-none"
        onClick={(e) => e.stopPropagation()}
      >
        {/* ── 标题栏 ── */}
        <div className="flex items-center justify-between mb-1">
          <div className="flex items-center gap-2">
            <div className="p-1.5 rounded-action bg-brand/15 text-brand">
              <CheckCheck size={18} strokeWidth={2.25} aria-hidden="true" />
            </div>
            <h3 className="text-base font-semibold text-[var(--color-text)]">
              选择对比简历
            </h3>
          </div>
          <button
            onClick={onCancel}
            aria-label="关闭"
            className="p-1.5 rounded-action text-[var(--color-text-secondary)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-secondary)] active:scale-[0.95] motion-reduce:active:scale-100 transition-all cursor-pointer"
          >
            <X size={16} strokeWidth={2.25} aria-hidden="true" />
          </button>
        </div>
        <p className="text-sm text-[var(--color-text-secondary)] mb-4">
          当前简历作为基准，再选择 {MIN_SELECT}-{MAX_SELECT} 份其他简历
        </p>

        {/* ── 内容区 ── */}
        {loading ? (
          <div className="flex flex-col items-center justify-center py-12 gap-2">
            <LoaderCircle
              size={24}
              className="animate-spin text-brand"
              aria-hidden="true"
            />
            <span className="text-sm text-[var(--color-text-secondary)]">
              加载中…
            </span>
          </div>
        ) : error ? (
          <div className="flex flex-col items-center justify-center py-12 gap-2">
            <div className="p-2 rounded-action bg-danger/15 text-danger">
              <TriangleAlert size={20} strokeWidth={2.25} aria-hidden="true" />
            </div>
            <span className="text-sm text-danger">{error}</span>
          </div>
        ) : resumes.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 gap-1">
            <span className="text-sm text-[var(--color-text-secondary)]">
              暂无可对比的简历
            </span>
            <span className="text-xs text-[var(--color-text-muted)]">
              需要至少再准备 1 份已完成的简历
            </span>
          </div>
        ) : (
          <>
            <div className="space-y-2 max-h-80 overflow-y-auto pr-1">
              {resumes.map((r) => {
                const checked = selectedIds.includes(r.id);
                const disabled = !checked && isFull;
                return (
                  <label
                    key={r.id}
                    className={`flex items-center gap-3 p-3 rounded-list border transition-all
                      ${checked
                        ? "bg-brand/10 border-brand/40"
                        : "bg-[var(--color-bg-secondary)] border-[var(--color-border)] hover:border-brand/30"}
                      ${disabled ? "opacity-40 cursor-not-allowed" : "cursor-pointer"}`}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      disabled={disabled}
                      onChange={() => toggle(r.id)}
                      className="sr-only"
                    />
                    {/* 自定义视觉勾选框 */}
                    <span
                      className={`w-5 h-5 shrink-0 rounded-md border flex items-center justify-center transition-colors
                        ${checked
                          ? "bg-brand border-brand"
                          : "border-[var(--color-border)]"}`}
                    >
                      {checked && (
                        <Check
                          size={14}
                          strokeWidth={2.25}
                          className="text-white"
                          aria-hidden="true"
                        />
                      )}
                    </span>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-[var(--color-text)] truncate">
                        {r.filename}
                      </p>
                      <p className="text-xs text-[var(--color-text-secondary)]">
                        {r.chunk_count} 个分块
                      </p>
                    </div>
                  </label>
                );
              })}
            </div>

            {/* ── 底部操作栏 ── */}
            <div className="flex items-center justify-between mt-6 pt-4 border-t border-[var(--color-border)]">
              <span className="text-sm text-[var(--color-text-secondary)]">
                已选{" "}
                <span className="tabular-nums font-medium text-[var(--color-text)]">
                  {selectedIds.length}
                </span>
                /{MAX_SELECT}
                {isFull && (
                  <span className="ml-1.5 text-xs text-warning">已达上限</span>
                )}
              </span>
              <div className="flex items-center gap-2">
                <button
                  onClick={onCancel}
                  className="px-3.5 py-1.5 text-sm font-medium rounded-action bg-[var(--color-bg-secondary)] hover:bg-[var(--color-bg-secondary)] border border-[var(--color-border)] text-[var(--color-text-secondary)] hover:text-[var(--color-text)] active:scale-[0.98] motion-reduce:active:scale-100 transition-all cursor-pointer"
                >
                  取消
                </button>
                <button
                  onClick={() => canConfirm && onConfirm(selectedIds)}
                  disabled={!canConfirm}
                  className="px-3.5 py-1.5 text-sm font-medium rounded-full bg-brand text-white active:scale-[0.98] motion-reduce:active:scale-100 transition-all cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  确认
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
