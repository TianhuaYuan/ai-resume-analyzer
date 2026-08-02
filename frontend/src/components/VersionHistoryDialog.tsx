/**
 * T18: 版本历史弹窗 — 展示简历的检索索引版本列表。
 *
 * 数据来自 GET /api/v1/resumes/{id}/versions（按 version 分组）：
 *   - version: 索引版本号（index_version，单调递增，独立于编辑器 document version）
 *   - is_latest: 是否最新版本
 *   - chunk_count: 该版本的分块数
 *   - sections: 该版本覆盖的简历节段列表
 *
 * 点击某个版本卡片可展开查看其来源节段。
 * 风格与 ChunksModal 保持一致（原生 <dialog> + Esc 关闭 + Tailwind）。
 */

import { useEffect, useRef, useState, useCallback } from "react";
import {
  X,
  ArrowClockwise,
  GitBranch,
  CaretDown,
  CaretUp,
} from "@phosphor-icons/react";
import {
  getResumeVersions,
  type ResumeVersionsResult,
} from "../api/resumes";

interface VersionHistoryDialogProps {
  resumeId: number;
  resumeFilename: string;
  open: boolean;
  onClose: () => void;
}

type Status = "loading" | "error" | "success";

export default function VersionHistoryDialog({
  resumeId,
  resumeFilename,
  open,
  onClose,
}: VersionHistoryDialogProps) {
  const [status, setStatus] = useState<Status>("loading");
  const [data, setData] = useState<ResumeVersionsResult | null>(null);
  const [error, setError] = useState("");
  const [expandedSet, setExpandedSet] = useState<Set<number>>(new Set());
  const cancelledRef = useRef(false);
  const dialogRef = useRef<HTMLDialogElement>(null);

  const load = useCallback(async () => {
    cancelledRef.current = false;
    setStatus("loading");
    setError("");
    try {
      const res = await getResumeVersions(resumeId);
      if (cancelledRef.current) return;
      setData(res);
      setStatus("success");
    } catch (err: unknown) {
      if (cancelledRef.current) return;
      setError(err instanceof Error ? err.message : "加载版本历史失败");
      setStatus("error");
    }
  }, [resumeId]);

  useEffect(() => {
    if (!open) return;
    setData(null);
    setError("");
    // 默认展开最新版本
    setExpandedSet(new Set());
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

  const handleToggle = (version: number) => {
    setExpandedSet((prev) => {
      const next = new Set(prev);
      if (next.has(version)) {
        next.delete(version);
      } else {
        next.add(version);
      }
      return next;
    });
  };

  const handleCancel = (e: React.FormEvent<HTMLDialogElement>) => {
    e.preventDefault();
    onClose();
  };

  if (!open) return null;

  const versions = data?.versions ?? [];

  return (
    <dialog
      ref={dialogRef}
      onCancel={handleCancel}
      onClose={handleCancel}
      className="fixed inset-0 z-50 m-0 w-full h-full p-0 overflow-hidden
        bg-black/60 backdrop-blur-sm motion-reduce:backdrop-blur-none"
      role="dialog"
      aria-modal="true"
      aria-label={`版本历史: ${resumeFilename}`}
    >
      <div
        className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2
          bg-[var(--color-surface)] border border-[var(--color-border)] rounded-2xl
          w-[calc(100vw-2rem)] sm:max-w-lg md:max-w-xl
          shadow-2xl
          animate-fade-in-up motion-reduce:animate-none
          flex flex-col overflow-hidden
          max-h-[80dvh] sm:max-h-[85dvh]"
      >
        {/* 头部 */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--color-border)] shrink-0">
          <div className="min-w-0 flex-1">
            <h3 className="text-base font-semibold text-[var(--color-text)] truncate">
              版本历史
            </h3>
            <p className="text-xs text-[var(--color-text-muted)] truncate mt-0.5">
              {resumeFilename}
              {status === "success" && data && (
                <span className="ml-2 text-[var(--color-text-secondary)]">
                  当前版本{" "}
                  <span className="text-[var(--color-text)] font-medium font-mono tabular-nums">
                    v{data.current_version}
                  </span>
                  {versions.length > 0 && (
                    <span className="ml-1.5">
                      共 <span className="text-[var(--color-text)] font-medium font-mono tabular-nums">{versions.length}</span> 个版本
                    </span>
                  )}
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
          className="flex-1 overflow-y-auto pl-6 pr-3 py-5"
          style={{ scrollbarGutter: "stable" }}
        >
          {status === "loading" && (
            <div className="space-y-3" aria-busy="true" aria-live="polite">
              <div className="h-14 rounded-lg animate-skeleton" />
              <div className="h-14 rounded-lg animate-skeleton" />
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

          {status === "success" && versions.length === 0 && (
            <div className="text-center py-12 text-[var(--color-text-muted)] text-sm">
              <GitBranch
                size={28}
                weight="duotone"
                className="mx-auto mb-3 opacity-60"
                aria-hidden="true"
              />
              暂无检索索引版本
              <p className="text-xs mt-1.5 opacity-80">
                首次问答 / 保存并完成时会自动建立索引
              </p>
            </div>
          )}

          {status === "success" && versions.length > 0 && (
            <div className="space-y-3.5">
              {versions.map((v) => {
                const expanded = expandedSet.has(v.version);
                const isCurrent = v.version === data?.current_version;
                return (
                  <div
                    key={v.version}
                    className="bg-white/[0.03] border border-[var(--color-border)] rounded-lg overflow-hidden"
                  >
                    <button
                      onClick={() => handleToggle(v.version)}
                      className="w-full flex items-center gap-3 px-4 py-3 text-left
                        hover:bg-white/[0.05]
                        active:scale-[0.99] motion-reduce:active:scale-100
                        transition-all cursor-pointer"
                      aria-expanded={expanded}
                    >
                      <span
                        className={`inline-flex items-center justify-center
                          text-[11px] font-mono font-medium tabular-nums
                          px-1.5 py-0.5 rounded shrink-0
                          border ${
                            isCurrent
                              ? "bg-brand/15 text-brand border-brand/25"
                              : "bg-[var(--color-bg-secondary)] text-[var(--color-text-muted)] border-[var(--color-border)]"
                          }`}
                      >
                        v{v.version}
                      </span>
                      <span className="flex-1 min-w-0">
                        <span className="flex items-center gap-2">
                          <span className="text-sm font-medium text-[var(--color-text)]">
                            {v.chunk_count} 个分块
                          </span>
                          {v.is_latest && (
                            <span
                              className="inline-flex items-center px-1.5 py-0.5 rounded
                                text-[10px] font-medium bg-emerald-500/15 text-emerald-300
                                border border-emerald-500/30"
                            >
                              最新
                            </span>
                          )}
                          {isCurrent && (
                            <span
                              className="inline-flex items-center px-1.5 py-0.5 rounded
                                text-[10px] font-medium bg-brand/15 text-brand
                                border border-brand/30"
                            >
                              当前
                            </span>
                          )}
                        </span>
                        <span className="block text-[11px] text-[var(--color-text-muted)] mt-0.5 truncate">
                          {v.sections.length > 0
                            ? v.sections.join(" · ")
                            : "(无节段信息)"}
                        </span>
                      </span>
                      {expanded ? (
                        <CaretUp
                          size={14}
                          weight="bold"
                          aria-hidden="true"
                          className="text-[var(--color-text-muted)] shrink-0"
                        />
                      ) : (
                        <CaretDown
                          size={14}
                          weight="bold"
                          aria-hidden="true"
                          className="text-[var(--color-text-muted)] shrink-0"
                        />
                      )}
                    </button>
                    {expanded && (
                      <div className="px-4 pb-3 pt-2 border-t border-[var(--color-border)]">
                        <p className="text-[11px] text-[var(--color-text-muted)] mb-2">
                          来源节段
                        </p>
                        {v.sections.length > 0 ? (
                          <div className="flex flex-wrap gap-1.5">
                            {v.sections.map((s) => (
                              <span
                                key={s}
                                className="inline-flex items-center px-2 py-1 rounded-md
                                  text-[11px] text-[var(--color-text-secondary)]
                                  bg-[var(--color-bg-secondary)] border border-[var(--color-border)]"
                              >
                                {s}
                              </span>
                            ))}
                          </div>
                        ) : (
                          <p className="text-xs text-[var(--color-text-muted)]">
                            暂无节段信息
                          </p>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </dialog>
  );
}
