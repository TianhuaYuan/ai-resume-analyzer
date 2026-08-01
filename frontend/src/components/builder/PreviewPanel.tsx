/**
 * T31: PreviewPanel — Builder 右侧 iframe 预览面板。
 *
 * 功能：
 * - iframe 加载 getPreviewUrl(resumeId)
 * - 手动刷新按钮
 * - 防抖自动刷新：父组件传入 previewKey，内容变更时 300ms 后自动重载
 * - 导出按钮：PDF / Markdown
 * - 可折叠面板（切换全宽/收起）
 * - iframe 加载中状态
 */

import { useState, useEffect, useRef, useCallback } from "react";
import {
  ArrowsClockwise,
  FilePdf,
  FileText,
  ArrowsInSimple,
  ArrowsOutSimple,
  SpinnerGap,
} from "@phosphor-icons/react";
import { fetchPreviewHtml, downloadExport } from "../../api/builder";
import type { ResumeModuleInput, ResumeStyle } from "../../api/builder";
import { trackEvent } from "../../api/analytics";

interface PreviewPanelProps {
  /** 简历 ID */
  resumeId: number;
  /** 预览刷新 key（内容变更时递增） */
  previewKey: number;
  /** 是否折叠 */
  collapsed: boolean;
  /** 切换折叠回调 */
  onToggleCollapse: () => void;
  /** 当前编辑数据（传入后用 POST 实时渲染，不读数据库） */
  modulesData?: { modules: ResumeModuleInput[]; style: ResumeStyle };
}

export function PreviewPanel({
  resumeId,
  previewKey,
  collapsed,
  onToggleCollapse,
  modulesData,
}: PreviewPanelProps) {
  // 预览 HTML（#7: fetch 带 header 拿 HTML → iframe srcDoc，避免 iframe src 无法带 Authorization）
  const [html, setHtml] = useState("");
  // iframe 加载状态
  const [loading, setLoading] = useState(true);
  // 预览错误
  const [previewError, setPreviewError] = useState("");
  // 导出状态
  const [exporting, setExporting] = useState<"pdf" | "markdown" | null>(null);
  const [exportError, setExportError] = useState("");

  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const loadPreview = useCallback(async () => {
    setLoading(true);
    setPreviewError("");
    try {
      const content = await fetchPreviewHtml(resumeId, modulesData);
      setHtml(content);
    } catch (e) {
      setPreviewError(e instanceof Error ? e.message : "预览加载失败");
      setHtml("");
    } finally {
      setLoading(false);
    }
  }, [resumeId, modulesData]);

  // 首次加载 + previewKey 变化 → 防抖 300ms 后重新获取预览
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      void loadPreview();
    }, previewKey === 0 ? 0 : 300);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [previewKey, loadPreview]);

  // 手动刷新
  const handleManualRefresh = useCallback(() => {
    void loadPreview();
  }, [loadPreview]);

  // 导出
  const handleExport = useCallback(
    async (format: "pdf" | "markdown") => {
      setExporting(format);
      setExportError("");
      try {
        await downloadExport(resumeId, format);
        // T37: 导出成功埋点（best-effort）
        void trackEvent("resume.export", undefined, { format });
      } catch (e) {
        setExportError(e instanceof Error ? e.message : "导出失败");
      } finally {
        setExporting(null);
      }
    },
    [resumeId],
  );

  // 折叠状态：只显示一个展开按钮
  if (collapsed) {
    return (
      <div className="flex flex-col items-center justify-center w-12
        border-l border-[var(--color-border)] bg-[var(--color-bg)] py-3 gap-3">
        <button
          onClick={onToggleCollapse}
          className="p-2 rounded-lg text-[var(--color-text-muted)]
            hover:text-indigo-400 hover:bg-indigo-500/10
            transition-all cursor-pointer"
          aria-label="展开预览"
          title="展开预览"
        >
          <ArrowsOutSimple size={16} weight="bold" aria-hidden="true" />
        </button>
        <span
          className="text-[10px] text-[var(--color-text-muted)] writing-mode-vertical
            [writing-mode:vertical-rl] tracking-wider"
        >
          预览
        </span>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full border-l border-[var(--color-border)] bg-[var(--color-bg)]">
      {/* 工具栏 */}
      <div className="shrink-0 flex items-center justify-between px-3 py-2.5
        border-b border-[var(--color-border)]">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-[var(--color-text-secondary)]">
            预览
          </span>
          {loading && (
            <SpinnerGap
              size={12}
              weight="bold"
              className="text-indigo-400 animate-spin"
              aria-hidden="true"
            />
          )}
        </div>

        <div className="flex items-center gap-1">
          {/* 导出 PDF */}
          <button
            onClick={() => handleExport("pdf")}
            disabled={exporting !== null}
            className="inline-flex items-center gap-1 px-2 py-1 rounded-md
              text-[11px] text-[var(--color-text-muted)]
              hover:text-red-400 hover:bg-red-500/8
              disabled:opacity-40 disabled:cursor-not-allowed
              transition-all cursor-pointer"
            aria-label="导出 PDF"
            title="导出 PDF"
          >
            {exporting === "pdf" ? (
              <SpinnerGap size={12} weight="bold" className="animate-spin" aria-hidden="true" />
            ) : (
              <FilePdf size={12} weight="regular" aria-hidden="true" />
            )}
            PDF
          </button>

          {/* 导出 Markdown */}
          <button
            onClick={() => handleExport("markdown")}
            disabled={exporting !== null}
            className="inline-flex items-center gap-1 px-2 py-1 rounded-md
              text-[11px] text-[var(--color-text-muted)]
              hover:text-indigo-400 hover:bg-indigo-500/8
              disabled:opacity-40 disabled:cursor-not-allowed
              transition-all cursor-pointer"
            aria-label="导出 Markdown"
            title="导出 Markdown"
          >
            {exporting === "markdown" ? (
              <SpinnerGap size={12} weight="bold" className="animate-spin" aria-hidden="true" />
            ) : (
              <FileText size={12} weight="regular" aria-hidden="true" />
            )}
            MD
          </button>

          {/* 手动刷新 */}
          <button
            onClick={handleManualRefresh}
            disabled={loading}
            className="p-1 rounded-md text-[var(--color-text-muted)]
              hover:text-indigo-400 hover:bg-indigo-500/8
              disabled:opacity-40 disabled:cursor-not-allowed
              transition-all cursor-pointer"
            aria-label="刷新预览"
            title="刷新预览"
          >
            <ArrowsClockwise
              size={14}
              weight="regular"
              className={loading ? "animate-spin" : ""}
              aria-hidden="true"
            />
          </button>

          {/* 收起按钮 */}
          <button
            onClick={onToggleCollapse}
            className="p-1 rounded-md text-[var(--color-text-muted)]
              hover:text-indigo-400 hover:bg-indigo-500/8
              transition-all cursor-pointer"
            aria-label="收起预览"
            title="收起预览"
          >
            <ArrowsInSimple size={14} weight="bold" aria-hidden="true" />
          </button>
        </div>
      </div>

      {/* 导出错误提示 */}
      {exportError && (
        <div className="shrink-0 px-3 py-1.5 bg-red-500/10 border-b border-red-500/20
          text-[11px] text-red-400">
          {exportError}
        </div>
      )}

      {/* iframe 预览区 */}
      <div className="flex-1 relative overflow-hidden">
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center
            bg-[var(--color-bg)] z-10">
            <div className="flex flex-col items-center gap-2">
              <span
                className="inline-block w-6 h-6 rounded-full border-2
                  border-indigo-400 border-t-transparent animate-spin"
                aria-hidden="true"
              />
              <span className="text-xs text-[var(--color-text-muted)]">
                加载预览...
              </span>
            </div>
          </div>
        )}
        {previewError && !loading && (
          <div className="absolute inset-0 flex items-center justify-center
            bg-[var(--color-bg)] z-10">
            <div className="flex flex-col items-center gap-2 px-6 text-center">
              <span className="text-xs text-red-400">{previewError}</span>
              <button
                onClick={handleManualRefresh}
                className="px-3 py-1.5 rounded-lg text-xs font-medium
                  bg-indigo-500/15 text-indigo-300 border border-indigo-500/30
                  hover:bg-indigo-500/25 transition-all cursor-pointer"
              >
                重试
              </button>
            </div>
          </div>
        )}
        {/* allow-same-origin + allow-scripts 组合会让 iframe 脚本逃逸沙箱访问父页面；
            预览 HTML 为纯静态渲染，仅 allow-scripts 即可在 opaque origin 隔离运行 */}
        <iframe
          title="简历预览"
          className="w-full h-full border-0"
          sandbox="allow-scripts"
          srcDoc={html || "<html><body style='background:#fff'></body></html>"}
        />
      </div>
    </div>
  );
}
