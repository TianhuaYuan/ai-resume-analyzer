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

  // Esc 关闭
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

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

  const handleOverlayClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (e.target === e.currentTarget) onClose();
  };

  if (!open) return null;

  return (
    <div
      onClick={handleOverlayClick}
      className="fixed inset-0 z-50 flex items-center justify-center
        bg-black/60 backdrop-blur-sm motion-reduce:backdrop-blur-none"
      role="dialog"
      aria-modal="true"
      aria-label={`简历分块预览: ${resumeFilename}`}
    >
      <div
        className="bg-[#1e293b] border border-white/10 rounded-2xl
          max-w-2xl w-full mx-4 shadow-2xl
          animate-fade-in-up motion-reduce:animate-none
          flex flex-col max-h-[85dvh]"
      >
        {/* 头部 */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/8 shrink-0">
          <div className="min-w-0 flex-1">
            <h3 className="text-base font-semibold text-slate-100 truncate">
              分块预览
            </h3>
            <p className="text-xs text-slate-500 truncate mt-0.5">
              {resumeFilename}
              {status === "success" && (
                <span className="ml-2 text-slate-400">
                  共 <span className="text-slate-200 font-medium">{chunks.length}</span> 个分块
                </span>
              )}
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label="关闭"
            className="ml-3 p-1.5 rounded-lg text-slate-400
              hover:text-slate-100 hover:bg-white/8
              active:scale-[0.95] motion-reduce:active:scale-100
              transition-all cursor-pointer shrink-0"
          >
            <X size={18} weight="bold" aria-hidden="true" />
          </button>
        </div>

        {/* 内容区 */}
        <div className="flex-1 overflow-y-auto px-6 py-5">
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
            <div className="text-center py-12 text-slate-500 text-sm">
              暂无分块数据
            </div>
          )}

          {status === "success" && chunks.length > 0 && (
            <div className="space-y-2.5">
              {chunks.map((chunk) => {
                const expanded = expandedSet.has(chunk.chunk_index);
                return (
                  <div
                    key={chunk.chunk_index}
                    className="bg-white/[0.03] border border-white/8 rounded-lg overflow-hidden"
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
                        <span className="block text-sm font-medium text-slate-200 truncate">
                          {chunk.section || "(无标题)"}
                        </span>
                        <span className="block text-[11px] text-slate-500 mt-0.5 font-mono">
                          chars {chunk.start_char}-{chunk.end_char}
                        </span>
                      </span>
                      {expanded ? (
                        <CaretUp
                          size={14}
                          weight="bold"
                          aria-hidden="true"
                          className="text-slate-500 shrink-0"
                        />
                      ) : (
                        <CaretDown
                          size={14}
                          weight="bold"
                          aria-hidden="true"
                          className="text-slate-500 shrink-0"
                        />
                      )}
                    </button>
                    {expanded && (
                      <div className="px-4 pb-3 pt-1 border-t border-white/5">
                        <p className="text-sm text-slate-300 leading-relaxed whitespace-pre-wrap">
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
    </div>
  );
}
