/**
 * AtsOptimizeDialog — 过机筛优化弹窗。
 *
 * 输入目标公司和岗位名称，自动生成 ATS 优化 prompt 发给 Builder Agent。
 */

import { useState, useEffect, useRef } from "react";
import { X, Funnel, Spinner } from "@phosphor-icons/react";

interface AtsOptimizeDialogProps {
  open: boolean;
  onClose: () => void;
  onOptimize: (company: string, position: string) => void;
}

export default function AtsOptimizeDialog({ open, onClose, onOptimize }: AtsOptimizeDialogProps) {
  const [company, setCompany] = useState("");
  const [position, setPosition] = useState("");
  const [loading, setLoading] = useState(false);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const companyRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open) {
      try { dialog.showModal(); } catch { dialog.open = true; }
      setTimeout(() => companyRef.current?.focus(), 100);
    } else {
      try { dialog.close(); } catch { dialog.open = false; }
    }
  }, [open]);

  const handleOptimize = () => {
    if (!company.trim() || !position.trim()) return;
    setLoading(true);
    onOptimize(company.trim(), position.trim());
    // 父组件负责关闭和发送，这里延迟关闭
    setTimeout(() => {
      setLoading(false);
      onClose();
    }, 500);
  };

  if (!open) return null;

  return (
    <dialog
      ref={dialogRef}
      onCancel={onClose}
      onClose={onClose}
      className="fixed inset-0 z-[60] m-0 w-full h-full p-0
        bg-black/30 backdrop-blur-sm motion-reduce:backdrop-blur-none"
      role="dialog"
      aria-modal="true"
      aria-label="过机筛优化"
    >
      <div
        className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2
          glass-card shadow-2xl
          max-w-md w-full mx-4
          animate-fade-in-up motion-reduce:animate-none"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--color-border)]">
          <div className="flex items-center gap-2">
            <Funnel size={18} weight="duotone" className="text-brand" />
            <h3 className="text-base font-semibold text-[var(--color-text)]">过机筛优化 AI</h3>
          </div>
          <button
            onClick={onClose}
            aria-label="关闭"
            className="p-1.5 rounded-lg text-[var(--color-text-secondary)]
              hover:text-[var(--color-text)] hover:bg-[var(--color-bg-secondary)] transition-all cursor-pointer"
          >
            <X size={18} weight="bold" />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-5 space-y-4">
          <p className="text-xs text-[var(--color-text-muted)]">
            输入目标公司和岗位信息，AI 将根据主流 ATS（Applicant Tracking System）算法为您优化简历
          </p>

          <div>
            <label className="block text-xs font-medium text-[var(--color-text-muted)] mb-1.5">
              目标公司 <span className="text-red-400">*</span>
            </label>
            <input
              ref={companyRef}
              type="text"
              value={company}
              onChange={(e) => setCompany(e.target.value)}
              placeholder="如：字节跳动"
              className="w-full px-3 py-2 rounded-xl bg-[#F2F2F7] border border-transparent
                text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)]
                focus:outline-none focus:bg-white focus:border-brand/40
                focus:ring-4 focus:ring-brand/15 transition-all duration-150"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-[var(--color-text-muted)] mb-1.5">
              目标岗位 <span className="text-red-400">*</span>
            </label>
            <input
              type="text"
              value={position}
              onChange={(e) => setPosition(e.target.value)}
              placeholder="如：后端工程师"
              className="w-full px-3 py-2 rounded-xl bg-[#F2F2F7] border border-transparent
                text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)]
                focus:outline-none focus:bg-white focus:border-brand/40
                focus:ring-4 focus:ring-brand/15 transition-all duration-150"
            />
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 px-6 py-4 border-t border-[var(--color-border)]">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-lg bg-[var(--color-bg-secondary)]
              text-xs text-[var(--color-text-secondary)] hover:bg-[#E5E5EA] transition-colors cursor-pointer"
          >
            取消
          </button>
          <button
            onClick={handleOptimize}
            disabled={loading || !company.trim() || !position.trim()}
            className="px-4 py-2 rounded-full bg-brand text-white text-xs font-medium
              hover:bg-[#0077ed] hover:scale-[1.02] transition-all duration-300 cursor-pointer
              disabled:opacity-40 disabled:cursor-not-allowed
              inline-flex items-center gap-2"
          >
            {loading && <Spinner size={12} className="animate-spin" weight="bold" />}
            {loading ? "优化中..." : "开始优化"}
          </button>
        </div>
      </div>
    </dialog>
  );
}
