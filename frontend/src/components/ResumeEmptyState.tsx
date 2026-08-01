interface ResumeEmptyStateProps {
  onCreate: () => void;
  onUpload: () => void;
  /** 上传/新建进行中时禁用按钮，防止重复点击 */
  uploading?: boolean;
}

/**
 * 引导首页的空状态：无简历时展示「新建简历 / 上传简历」两个入口。
 * 视觉沿用 mono-rule + font-display 大字 + mono-btn-primary 的 monochrome 风格。
 */
export default function ResumeEmptyState({
  onCreate,
  onUpload,
  uploading = false,
}: ResumeEmptyStateProps) {
  return (
    <div className="py-16 md:py-32 flex flex-col md:flex-row md:items-center md:justify-between gap-12">
      <div className="flex-1">
        <hr className="mono-rule mb-8 max-w-xs" />
        <p className="font-display text-3xl md:text-5xl font-bold tracking-tight text-[var(--color-text)] mb-6 leading-tight">
          开始你的<br />简历之旅
        </p>
        <p
          className="text-base md:text-lg text-[var(--color-text-secondary)] mb-8 max-w-md leading-relaxed"
          style={{ fontFamily: "var(--font-body)" }}
        >
          从零开始用编辑器创建一份专业简历，或上传已有简历让 AI 分析优化。
        </p>
        <div className="flex items-center gap-4 flex-wrap">
          <button onClick={onCreate} disabled={uploading} className="mono-btn-primary">
            新建简历 →
          </button>
          <button
            onClick={onUpload}
            disabled={uploading}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm
              border border-[var(--color-text)] text-[var(--color-text)]
              hover:bg-[var(--color-text)] hover:text-[var(--color-bg)]
              disabled:opacity-50 disabled:cursor-not-allowed
              transition-colors duration-100 cursor-pointer"
          >
            上传简历
          </button>
        </div>
      </div>
      <div className="flex-1 flex justify-center">
        <div className="w-48 h-48 md:w-64 md:h-64 border-2 border-[var(--color-text)] flex items-center justify-center">
          <svg viewBox="0 0 64 64" className="w-24 h-24 md:w-32 md:h-32">
            <polygon points="32,6 54,18 32,30 10,18" fill="var(--color-text)" opacity="0.1"/>
            <polygon points="10,18 32,30 32,54 10,42" fill="var(--color-text)" opacity="0.1"/>
            <polygon points="32,30 54,18 54,42 32,54" fill="var(--color-text)" opacity="0.1"/>
            <polygon points="32,6 54,18 32,30 10,18" fill="none" stroke="var(--color-text)" strokeWidth="1"/>
            <polygon points="10,18 32,30 32,54 10,42" fill="none" stroke="var(--color-text)" strokeWidth="1"/>
            <polygon points="32,30 54,18 54,42 32,54" fill="none" stroke="var(--color-text)" strokeWidth="1"/>
          </svg>
        </div>
      </div>
    </div>
  );
}
