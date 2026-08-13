/**
 * A4PreviewPanel — A4 预览面板（真实多页容器 + 自动压缩）。
 *
 * 分页方案：PaginatedResumePreview（隐藏测量层 + 逐 section 装箱 + 每页独立 A4 纸张）。
 * 旧的「单长 DOM + 红色虚线」已废弃 —— 虚线会横穿文字且与打印 PDF 分页错位。
 *
 * - 自动压缩：内容超出目标页数时 transform scale 压缩，下限 0.75
 * - 打印导出：transform → zoom 转换（借鉴 magic-resume，zoom 参与布局所以分页准确）
 * - PDF/MD 导出保留（后端 WeasyPrint / Markdown）
 */

import { useState, useCallback, memo } from "react";
import { FileDown, FileText, Minimize2, Maximize2, Loader, Printer, AlignJustify } from "lucide-react";
import { downloadExport } from "../../api/builder";
import { PaginatedResumePreview, type PaginatedPreviewState } from "./PaginatedResumePreview";
import { exportResumeToBrowserPrint } from "../../utils/printResume";
import { trackEvent } from "../../api/analytics";
import type { ModuleType, ResumeModule, ResumeStyle } from "../../api/builder";

type ZoomLevel = 40 | 50 | 75 | 100;
const ZOOM_OPTIONS: ZoomLevel[] = [40, 50, 75, 100];

interface A4PreviewPanelProps {
  resumeId: number;
  /** 预览刷新 key（兼容旧接口；React 直接渲染后实际不依赖） */
  previewKey: number;
  collapsed: boolean;
  onToggleCollapse: () => void;
  /** 当前编辑数据（modules + style），实时渲染 */
  modulesData?: { modules: ResumeModuleInputLite[]; style: ResumeStyle };
  /** 点击预览板块回调（聚焦编辑器对应模块） */
  onSelectSection?: (moduleType: ModuleType) => void;
}

type ResumeModuleInputLite = Pick<ResumeModule, "module_type" | "content" | "sort_order">;

export const A4PreviewPanel = memo(function A4PreviewPanel({
  resumeId,
  previewKey: _previewKey,
  collapsed,
  onToggleCollapse,
  modulesData,
  onSelectSection,
}: A4PreviewPanelProps) {
  const [zoom, setZoom] = useState<ZoomLevel>(() =>
    typeof window !== "undefined" && window.innerWidth < 640 ? 40 : 75,
  );
  /** 自动压缩目标页数：0 = 关闭 */
  const [fitPages, setFitPages] = useState(0);
  const [exporting, setExporting] = useState<"pdf" | "markdown" | "print" | null>(null);
  const [exportError, setExportError] = useState("");
  const [pageState, setPageState] = useState<PaginatedPreviewState>({
    pageCount: 0,
    isScaled: false,
    cannotFit: false,
    scaleFactor: 1,
  });

  const modules = modulesData?.modules ?? [];
  const style = modulesData?.style;

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

  const handlePrint = useCallback(async () => {
    setExporting("print");
    setExportError("");
    try {
      await exportResumeToBrowserPrint({ title: "简历" });
      void trackEvent("resume.export", undefined, { format: "print" });
    } catch (e) {
      setExportError(e instanceof Error ? e.message : "打印失败");
    } finally {
      setExporting(null);
    }
  }, []);

  if (collapsed) {
    return (
      <div className="flex flex-col items-center justify-center w-12
        border-l border-[var(--color-border)] bg-[var(--color-bg)] py-3 gap-3">
        <button
          onClick={onToggleCollapse}
          className="p-2 rounded-action text-[var(--color-text-muted)]
            hover:text-brand hover:bg-brand/10 transition-all cursor-pointer"
          aria-label="展开预览"
          title="展开预览"
        >
          <Maximize2 size={16} strokeWidth={2.25} aria-hidden="true" />
        </button>
        <span className="text-[10px] text-[var(--color-text-muted)] writing-mode-vertical
          [writing-mode:vertical-rl] tracking-wider">
          预览
        </span>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full border-l border-[var(--color-border)] bg-[var(--color-bg)]">
      {/* 工具栏 */}
      <div className="shrink-0 flex flex-wrap items-center justify-between gap-2 px-2 sm:px-3 py-2.5
        border-b border-[var(--color-border)]">
        <div className="flex w-full sm:w-auto items-center justify-between sm:justify-start gap-2">
          <span className="text-xs font-semibold text-[var(--color-text-secondary)]">预览</span>
          {pageState.pageCount > 0 && (
            <span className="text-[10px] text-[var(--color-text-muted)] tabular-nums">
              共 {pageState.pageCount} 页
            </span>
          )}
          {/* 自动压缩：关闭 → 1 页 → 2 页 → 关闭 */}
          <button
            onClick={() => setFitPages((v) => (v === 0 ? 1 : v === 1 ? 2 : 0))}
            className={`btn-tool text-[10px] ${fitPages > 0 ? "btn-tool-active" : ""}`}
            aria-pressed={fitPages > 0}
            title="内容超出目标页数时自动压缩（点击切换 1 页 / 2 页 / 关闭）"
          >
            <AlignJustify size={11} fill={fitPages > 0 ? "currentColor" : "none"} aria-hidden="true" />
            {fitPages === 0 ? "自动压缩" : `压到 ${fitPages} 页`}
          </button>
          {pageState.isScaled && (
            <span className="text-[10px] text-brand tabular-nums">
              {Math.round(pageState.scaleFactor * 100)}%
            </span>
          )}
        </div>

        <div className="flex w-full sm:w-auto flex-wrap items-center gap-1">
          {/* 缩放控制 */}
          <div className="flex items-center gap-0.5 mr-1 px-1 py-0.5 rounded-full
            bg-[var(--color-bg-secondary)] border border-[var(--color-border)]">
            {ZOOM_OPTIONS.map((z) => (
              <button
                key={z}
                onClick={() => setZoom(z)}
                className={`px-1.5 py-0.5 rounded-full text-[10px] font-medium transition-all cursor-pointer
                  ${zoom === z
                    ? "bg-brand/10 text-brand"
                    : "text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
                  }`}
                aria-label={`缩放 ${z}%`}
                aria-pressed={zoom === z}
              >
                {z}%
              </button>
            ))}
          </div>

          {/* 打印 */}
          <button
            onClick={handlePrint}
            disabled={exporting !== null}
            className="btn-tool text-[11px]"
            aria-label="打印简历"
            title="浏览器打印"
          >
            {exporting === "print" ? (
              <Loader size={12} strokeWidth={2.25} className="animate-spin" aria-hidden="true" />
            ) : (
              <Printer size={12} aria-hidden="true" />
            )}
            打印
          </button>

          {/* 导出 PDF */}
          <button
            onClick={() => handleExport("pdf")}
            disabled={exporting !== null}
            className="inline-flex items-center gap-1 px-2 py-1 rounded-md
              text-[11px] text-[var(--color-text-muted)] hover:text-danger hover:bg-danger/8
              disabled:opacity-40 disabled:cursor-not-allowed transition-all cursor-pointer"
            aria-label="导出 PDF"
            title="导出 PDF（后端 WeasyPrint）"
          >
            {exporting === "pdf" ? (
              <Loader size={12} strokeWidth={2.25} className="animate-spin" aria-hidden="true" />
            ) : (
              <FileDown size={12} aria-hidden="true" />
            )}
            PDF
          </button>

          {/* 导出 Markdown */}
          <button
            onClick={() => handleExport("markdown")}
            disabled={exporting !== null}
            className="btn-tool text-[11px]"
            aria-label="导出 Markdown"
            title="导出 Markdown"
          >
            {exporting === "markdown" ? (
              <Loader size={12} strokeWidth={2.25} className="animate-spin" aria-hidden="true" />
            ) : (
              <FileText size={12} aria-hidden="true" />
            )}
            MD
          </button>

          {/* 收起 */}
          <button
            onClick={onToggleCollapse}
            className="btn-tool-icon"
            aria-label="收起预览"
            title="收起预览"
          >
            <Minimize2 size={14} strokeWidth={2.25} aria-hidden="true" />
          </button>
        </div>
      </div>

      {/* 导出错误提示 */}
      {exportError && (
        <div className="shrink-0 px-3 py-1.5 bg-danger/10 border-b border-danger/20
          text-[11px] text-danger">
          {exportError}
        </div>
      )}

      {/* 压缩已达下限提示 */}
      {pageState.cannotFit && (
        <div className="shrink-0 px-3 py-1.5 bg-warning/10 border-b border-warning/20
          text-[11px] text-warning">
          内容过多，已压缩到最小缩放（75%）仍放不下，建议精简内容或调小字号
        </div>
      )}

      {/* A4 预览区：真实多页容器，#resume-preview 供打印/导出取 DOM */}
      <div
        id="resume-preview"
        className="flex-1 overflow-auto bg-[var(--color-bg)] flex justify-center p-2 sm:p-6"
      >
        <PaginatedResumePreview
          modules={modules as ResumeModule[]}
          style={style ?? ({} as ResumeStyle)}
          zoom={zoom / 100}
          fitPages={fitPages}
          interactive
          onSelectSection={onSelectSection}
          onStateChange={setPageState}
        />
      </div>
    </div>
  );
});
