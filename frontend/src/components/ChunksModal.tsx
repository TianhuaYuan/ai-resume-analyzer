import { useEffect, useRef, useState, useCallback } from "react";
import { X, ArrowClockwise, CaretDown, CaretUp } from "@phosphor-icons/react";
import { getChunks, type ChunkItem } from "../api/resumes";

interface ChunksModalProps {
  resumeId: number;
  resumeFilename: string;
  open: boolean;
  onClose: () => void;
}

type Status = "loading" | "error" | "success";

export default function ChunksModal({
  resumeId,
  resumeFilename,
  open,
  onClose,
}: ChunksModalProps) {
  const [status, setStatus] = useState<Status>("loading");
  const [chunks, setChunks] = useState<ChunkItem[]>([]);
  const [error, setError] = useState("");
  const [expandedSet, setExpandedSet] = useState<Set<number>>(new Set());
  const cancelledRef = useRef(false);
  const dialogRef = useRef<HTMLDialogElement>(null);

  const load = useCallback(async () => {
    cancelledRef.current = false;
    setStatus("loading");
    setError("");
    try {
      const res = await getChunks(resumeId);
      if (cancelledRef.current) return;
      setChunks(res.chunks);
      setStatus("success");
    } catch (err: unknown) {
      if (cancelledRef.current) return;
      setError(err instanceof Error ? err.message : "加载分块失败");
      setStatus("error");
    }
  }, [resumeId]);

  useEffect(() => {
    if (!open) return;
    setChunks([]);
    setError("");
    setExpandedSet(new Set());
    load();
    return () => {
      cancelledRef.current = true;
    };
  }, [open, load]);

  // P3-6：使用原生 <dialog>，showModal/close 控制，Esc 原生支持
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

  const handleToggle = (chunkIndex: number) => {
    setExpandedSet((prev) => {
      const next = new Set(prev);
      if (next.has(chunkIndex)) {
        next.delete(chunkIndex);
      } else {
        next.add(chunkIndex);
      }
      return next;
    });
  };

  const handleCancel = (e: React.FormEvent<HTMLDialogElement>) => {
    e.preventDefault();
    onClose();
  };

  if (!open) return null;

  return (
    <dialog
      ref={dialogRef}
      onCancel={handleCancel}
      onClose={handleCancel}
      className="fixed inset-0 z-50 m-0 w-full h-full p-0 overflow-hidden
        bg-black/60 backdrop-blur-sm motion-reduce:backdrop-blur-none"
      role="dialog"
      aria-modal="true"
      aria-label={`简历分块预览: ${resumeFilename}`}
    >
      <div
        className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2
          bg-[var(--color-surface)] border border-[var(--color-border)] rounded-2xl
          w-[calc(100vw-2rem)] sm:max-w-lg md:max-w-2xl
          shadow-2xl
          animate-fade-in-up motion-reduce:animate-none
          flex flex-col overflow-hidden
          max-h-[80dvh] sm:max-h-[85dvh] md:max-h-[82dvh]"
      >
        {/* 头部 */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--color-border)] shrink-0">
          <div className="min-w-0 flex-1">
            <h3 className="text-base font-semibold text-[var(--color-text)] truncate">
              分块预览
            </h3>
            <p className="text-xs text-[var(--color-text-muted)] truncate mt-0.5">
              {resumeFilename}
              {status === "success" && (
                <span className="ml-2 text-[var(--color-text-secondary)]">
                  共 <span className="text-[var(--color-text)] font-medium">{chunks.length}</span> 个分块
                </span>
              )}
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label="关闭"
            className="ml-3 p-1.5 rounded-lg text-[var(--color-text-secondary)]
              hover:text-[var(--color-text)] hover:bg-white/8
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
              <div className="h-12 rounded-lg animate-skeleton" />
              <div className="h-12 rounded-lg animate-skeleton" />
              <div className="h-12 rounded-lg animate-skeleton" />
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

          {status === "success" && chunks.length === 0 && (
            <div className="text-center py-12 text-[var(--color-text-muted)] text-sm">
              暂无分块数据
            </div>
          )}

          {status === "success" && chunks.length > 0 && (
            <div className="space-y-3.5">
              {chunks.map((chunk) => {
                const expanded = expandedSet.has(chunk.chunk_index);
                return (
                  <div
                    key={chunk.chunk_index}
                    className="bg-white/[0.03] border border-[var(--color-border)] rounded-lg overflow-hidden"
                  >
                    <button
                      onClick={() => handleToggle(chunk.chunk_index)}
                      className="w-full flex items-center gap-3 px-4 py-3 text-left
                        hover:bg-white/[0.05]
                        active:scale-[0.99] motion-reduce:active:scale-100
                        transition-all cursor-pointer"
                      aria-expanded={expanded}
                    >
                      <span
                        className="inline-flex items-center justify-center
                          text-[11px] font-mono font-medium
                          px-1.5 py-0.5 rounded
                          bg-indigo-500/15 text-indigo-300
                          border border-indigo-500/25
                          shrink-0"
                      >
                        #{chunk.chunk_index}
                      </span>
                      <span className="flex-1 min-w-0">
                        <span className="block text-sm font-medium text-[var(--color-text)] truncate">
                          {chunk.section || "(无标题)"}
                        </span>
                        <span className="block text-[11px] text-[var(--color-text-muted)] mt-0.5 font-mono">
                          chars {chunk.start_char}-{chunk.end_char}
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
                      <div className="px-4 pb-3 pt-1 border-t border-[var(--color-border)]">
                        <p className="text-sm text-[var(--color-text-secondary)] leading-relaxed whitespace-pre-wrap">
                          {chunk.text}
                        </p>
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
