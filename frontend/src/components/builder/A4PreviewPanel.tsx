/**
 * Task 1: A4PreviewPanel — A4 格式预览面板。
 *
 * 在 PreviewPanel 基础上增加：
 * - A4 页面比例（210mm × 297mm ≈ 1:1.414）
 * - 缩放控制（50% / 75% / 100%，默认 75%）
 * - 页面阴影 + 居中显示
 *
 * 保留：POST 实时渲染（300ms 防抖）、PDF/MD 导出、折叠/展开。
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

type ZoomLevel = 50 | 75 | 100;

const ZOOM_OPTIONS: ZoomLevel[] = [50, 75, 100];

interface A4PreviewPanelProps {
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

export function A4PreviewPanel({
  resumeId,
  previewKey,
  collapsed,
  onToggleCollapse,
  modulesData,
}: A4PreviewPanelProps) {
  const [html, setHtml] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [previewError, setPreviewError] = useState("");
  const [exporting, setExporting] = useState<"pdf" | "markdown" | null>(null);
  const [exportError, setExportError] = useState("");
  const [zoom, setZoom] = useState<ZoomLevel>(75);

  // ref 持有最新 modulesData，使 loadPreview 不依赖 modulesData → useCallback 引用稳定
  const modulesDataRef = useRef(modulesData);
  modulesDataRef.current = modulesData;
  // 是否已有内容（区分首次加载 vs 刷新，避免 loading 遮罩闪烁）
  const hasContentRef = useRef(false);
  // 请求取消：新请求发出时作废旧请求，避免竞态
  const requestIdRef = useRef(0);

  const loadPreview = useCallback(async () => {
    const currentRequestId = ++requestIdRef.current;
    // 首次加载显示全屏 loading；后续刷新只显示小 spinner
    if (!hasContentRef.current) {
      setLoading(true);
    } else {
      setRefreshing(true);
    }
    setPreviewError("");
    try {
      const content = await fetchPreviewHtml(resumeId, modulesDataRef.current);
      // 作废的请求回来后丢弃结果
      if (currentRequestId !== requestIdRef.current) return;
      setHtml(content);
      hasContentRef.current = Boolean(content);
    } catch (e) {
      if (currentRequestId !== requestIdRef.current) return;
      setPreviewError(e instanceof Error ? e.message : "预览加载失败");
      setHtml("");
    } finally {
      if (currentRequestId === requestIdRef.current) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, [resumeId]);

  // previewKey 变化时立即加载（防抖由 BuilderPage 600ms 控制，此处不再重复防抖）
  useEffect(() => {
    void loadPreview();
  }, [previewKey, loadPreview]);

  const handleManualRefresh = useCallback(() => {
    void loadPreview();
  }, [loadPreview]);

  const handleExport = useCallback(
    async (format: "pdf" | "markdown") => {
      setExporting(format);
      setExportError("");
      try {
        await downloadExport(resumeId, format);
        void trackEvent("resume.export", undefined, { format });
      } catch (e) {
        setExportError(e instanceof Error ? e.message : "导出失败");
      } finally {
        setExporting(null);
      }
    },
    [resumeId],
  );

  // 折叠状态：只显示展开按钮
  if (collapsed) {
    return (
      <div className="flex flex-col items-center justify-center w-12
        border-l border-[var(--color-border)] bg-[var(--color-bg)] py-3 gap-3">
        <button
          onClick={onToggleCollapse}
          className="p-2 rounded-lg text-[var(--color-text-muted)]
            hover:text-brand hover:bg-brand/10
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

  // A4 比例：宽 210mm，高 297mm → 比例 1:1.4142
  // 缩放后宽度 = 基准宽度 × zoom%
  // 基准宽度取 210mm 对应的像素值（约 794px @ 96dpi）
  const A4_BASE_WIDTH = 794; // 210mm @ 96dpi
  const scaledWidth = (A4_BASE_WIDTH * zoom) / 100;
  const scaledHeight = scaledWidth * 1.4142;

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
              className="text-brand animate-spin"
              aria-hidden="true"
            />
          )}
          {refreshing && !loading && (
            <SpinnerGap
              size={12}
              weight="bold"
              className="text-brand/60 animate-spin"
              aria-hidden="true"
            />
          )}
        </div>

        <div className="flex items-center gap-1">
          {/* 缩放控制 */}
          <div className="flex items-center gap-0.5 mr-1 px-1 py-0.5 rounded-md
            bg-[var(--color-bg-secondary)] border border-[var(--color-border)]">
            {ZOOM_OPTIONS.map((z) => (
              <button
                key={z}
                onClick={() => setZoom(z)}
                className={`px-1.5 py-0.5 rounded text-[10px] font-medium transition-all cursor-pointer
                  ${zoom === z
                    ? "bg-brand/10 text-brand"
                    : "text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-secondary)]"
                  }`}
                aria-label={`缩放 ${z}%`}
                aria-pressed={zoom === z}
              >
                {z}%
              </button>
            ))}
          </div>

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
              hover:text-brand hover:bg-brand/10
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
              hover:text-brand hover:bg-brand/10
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
              hover:text-brand hover:bg-brand/10
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

      {/* A4 预览区 — 可滚动，居中显示 A4 页面 */}
      <div className="flex-1 overflow-auto bg-[var(--color-bg)] flex justify-center p-4">
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center
            bg-[var(--color-bg)] z-10">
            <div className="flex flex-col items-center gap-2">
              <span
                className="inline-block w-6 h-6 rounded-full border-2
                  border-brand border-t-transparent animate-spin"
                aria-hidden="true"
              />
              <span className="text-xs text-[var(--color-text-muted)]">
                加载预览...
              </span>
            </div>
          </div>
        )}
        {previewError && !loading && (
          <div className="flex items-center justify-center w-full h-full">
            <div className="flex flex-col items-center gap-2 px-6 text-center">
              <span className="text-xs text-red-400">{previewError}</span>
              <button
                onClick={handleManualRefresh}
                className="px-3 py-1.5 rounded-lg text-xs font-medium
                  bg-brand/10 text-brand border border-brand/30
                  hover:bg-brand/20 transition-all cursor-pointer"
              >
                重试
              </button>
            </div>
          </div>
        )}
        {/* A4 页面容器 */}
        <div
          className="bg-white shrink-0 transition-transform duration-200"
          style={{
            width: `${scaledWidth}px`,
            minHeight: `${scaledHeight}px`,
            boxShadow: "0 4px 24px rgba(0, 0, 0, 0.3), 0 1px 4px rgba(0, 0, 0, 0.2)",
            borderRadius: "2px",
          }}
        >
          <iframe
            title="简历预览"
            className="w-full h-full border-0"
            sandbox="allow-scripts"
            srcDoc={html || "<html><body style='background:#fff;margin:0;padding:16mm'></body></html>"}
            style={{
              width: `${A4_BASE_WIDTH}px`,
              height: `${A4_BASE_WIDTH * 1.4142}px`,
              transform: `scale(${zoom / 100})`,
              transformOrigin: "top left",
            }}
          />
        </div>
      </div>
    </div>
  );
}
