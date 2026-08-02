import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, Gauge, ArrowsClockwise } from "@phosphor-icons/react";
import type { QuotaResponse } from "../api/qa";

interface Props {
  open: boolean;
  onClose: () => void;
}

function formatResetAt(resetAt: string | null): string {
  if (!resetAt) return "—";
  const d = new Date(resetAt);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export default function UsageDialog({ open, onClose }: Props) {
  const [quota, setQuota] = useState<QuotaResponse | null>(null);
  const [loading, setLoading] = useState(false);

  const fetchQuota = async () => {
    setLoading(true);
    try {
      const { getQuota } = await import("../api/qa");
      const data = await getQuota();
      setQuota(data);
    } catch {
      // 静默失败，保留已有数据
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open) void fetchQuota();
  }, [open]);

  const percent =
    quota && quota.limit > 0
      ? Math.min(100, Math.round((quota.used / quota.limit) * 100))
      : 0;

  const isLow = !!quota && quota.remaining < quota.limit * 0.1;
  const isMedium = !!quota && quota.remaining < quota.limit * 0.3;
  const barColor = isLow
    ? "bg-red-500"
    : isMedium
      ? "bg-yellow-500"
      : "bg-brand";

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4"
          onClick={onClose}
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 20 }}
            transition={{ duration: 0.2 }}
            className="w-full max-w-sm bg-[var(--color-bg)] border border-[var(--color-border)] rounded-2xl shadow-2xl overflow-hidden"
            data-testid="usage-dialog"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--color-border)]">
              <h2 className="text-lg font-semibold text-[var(--color-text)] flex items-center gap-2">
                <Gauge className="w-5 h-5 text-brand" weight="duotone" aria-hidden="true" />
                Token 用量
              </h2>
              <button
                onClick={onClose}
                className="text-[var(--color-text-muted)] hover:text-[var(--color-text)] transition-colors cursor-pointer"
                aria-label="关闭"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="p-5 space-y-5">
              {!quota ? (
                <div className="flex flex-col items-center gap-3 py-6">
                  <span className="inline-block w-6 h-6 rounded-full border-2 border-brand border-t-transparent animate-spin" />
                  <span className="text-xs text-[var(--color-text-muted)]">加载中...</span>
                </div>
              ) : !quota.enabled ? (
                <div className="text-center py-6">
                  <p className="text-sm text-[var(--color-text-secondary)]">
                    当前未启用每日额度限制
                  </p>
                  <p className="text-xs text-[var(--color-text-muted)] mt-1">
                    你可以放心使用，无需担心 token 消耗
                  </p>
                </div>
              ) : (
                <>
                  {/* 用量概览 */}
                  <div className="text-center">
                    <p className="text-4xl font-semibold text-[var(--color-text)] tabular-nums">
                      {quota.used.toLocaleString()}
                      <span className="text-sm font-normal text-[var(--color-text-muted)]">
                        {" "}
                        / {quota.limit.toLocaleString()}
                      </span>
                    </p>
                    <p className="text-xs text-[var(--color-text-muted)] mt-1">今日已用 tokens</p>
                  </div>

                  {/* 进度条 */}
                  <div className="h-2 rounded-full bg-[var(--color-bg-secondary)] overflow-hidden">
                    <motion.div
                      initial={{ width: 0 }}
                      animate={{ width: `${percent}%` }}
                      transition={{ duration: 0.6, ease: "easeOut" }}
                      className={`h-full rounded-full ${barColor}`}
                    />
                  </div>

                  {/* 明细 */}
                  <div className="grid grid-cols-2 gap-3 text-center">
                    <div className="p-3 rounded-xl bg-[var(--color-bg-secondary)]">
                      <p className="text-base font-semibold text-[var(--color-text)] tabular-nums">
                        {quota.remaining.toLocaleString()}
                      </p>
                      <p className="text-[10px] text-[var(--color-text-muted)] mt-0.5">剩余额度</p>
                    </div>
                    <div className="p-3 rounded-xl bg-[var(--color-bg-secondary)]">
                      <p className="text-base font-semibold text-[var(--color-text)] tabular-nums">
                        {percent}%
                      </p>
                      <p className="text-[10px] text-[var(--color-text-muted)] mt-0.5">已用比例</p>
                    </div>
                  </div>

                  <div className="flex items-center justify-between text-xs">
                    <span className="text-[var(--color-text-muted)]">额度重置时间</span>
                    <span className="text-[var(--color-text-secondary)] font-medium tabular-nums">
                      {formatResetAt(quota.reset_at)}
                    </span>
                  </div>
                </>
              )}

              <button
                onClick={() => void fetchQuota()}
                disabled={loading}
                className="w-full flex items-center justify-center gap-1.5 h-9 bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)] rounded-lg text-xs font-medium transition-colors hover:bg-[var(--color-border)] disabled:opacity-50 cursor-pointer"
              >
                <ArrowsClockwise
                  className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`}
                  aria-hidden="true"
                />
                {loading ? "刷新中..." : "刷新"}
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
