/**
 * templateBaseStyles — 共享模板基础 CSS（复刻后端 backend/templates/*.html 的通用样式）。
 *
 * 全部用 CSS 变量（--font-size/--accent-color 等）驱动，由 ResumeTemplateView 注入到容器。
 * 各模板在此基础上追加自己的布局变体样式。
 */

export const TEMPLATE_BASE_STYLES = `
  /* 只重置模板内部元素，禁止全局 * 污染页面其他组件 */
  .resume-template,
  .resume-template * {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
  }
  /* 根容器：白底铺满全部页面高度（多页时避免透明背景） */
  .resume-template-root {
    background: #fff;
    width: 100%;
  }
  .resume-template {
    font-family: var(--font-family), "PingFang SC", "Microsoft YaHei", sans-serif;
    font-size: var(--font-size);
    line-height: var(--line-height);
    color: #2d3748;
    background: #fff;
    word-break: break-word;
    overflow-wrap: break-word;
    width: 100%;
  }
  .resume-container { width: 100%; margin: 0 auto; }

  /* ── 头部：姓名 + 求职意向 + 联系方式 ── */
  .basic-header {
    padding-bottom: 14px;
    margin-bottom: var(--section-spacing);
  }
  .basic-header-line { display: flex; align-items: center; gap: 12px; }
  .basic-avatar { width: 80px; height: 80px; border-radius: 50%; object-fit: cover; }
  .basic-name {
    font-size: calc(var(--font-size) * 1.9);
    font-weight: 700;
    letter-spacing: 2px;
    color: #1a202c;
  }
  .basic-job-title {
    color: var(--accent-color);
    font-weight: 600;
    font-size: calc(var(--font-size) * 1.1);
    margin-top: 4px;
  }
  .basic-contact {
    color: #4a5568;
    font-size: calc(var(--font-size) * 0.95);
    margin-top: 6px;
    line-height: 1.8;
  }
  .basic-links { color: #4a5568; font-size: calc(var(--font-size) * 0.95); margin-top: 3px; }
  .basic-links a { color: var(--accent-color); text-decoration: none; }
  .basic-summary {
    color: #4a5568;
    margin-top: 8px;
    font-size: calc(var(--font-size) * 0.98);
    text-align: left;
    white-space: pre-wrap;
  }
  .basic-custom-fields {
    color: #4a5568;
    font-size: calc(var(--font-size) * 0.95);
    margin-top: 3px;
  }

  /* ── 章节：标题 + 内容 ── */
  .module {
    margin-bottom: var(--section-spacing);
    padding-bottom: 8px;
    break-inside: avoid;
  }
  .module-title {
    font-size: calc(var(--font-size) * 1.12);
    color: #1a202c;
    font-weight: 700;
    letter-spacing: 1px;
    margin-bottom: 8px;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .module-title::after {
    content: "";
    flex: 1;
    height: 2px;
    background: var(--accent-color);
    opacity: 0.35;
  }
  .module-content { padding-left: 2px; }

  /* ── 条目通用 ── */
  .edu-item, .work-item, .proj-item, .club-item {
    margin-bottom: calc(var(--section-spacing) * 1.1);
    break-inside: avoid;
  }
  .edu-header, .work-header, .proj-header {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 12px;
  }
  .edu-school, .work-company, .proj-name, .club-name {
    font-weight: 600;
    color: #1a202c;
    font-size: calc(var(--font-size) * 1.02);
  }
  .edu-date, .work-date, .proj-date, .club-date {
    color: #a0aec0;
    font-size: calc(var(--font-size) * 0.88);
    white-space: nowrap;
  }
  .edu-info, .work-position, .proj-role, .club-role {
    color: var(--accent-color);
    font-size: calc(var(--font-size) * 0.95);
    font-weight: 500;
    margin-top: 2px;
  }
  .work-desc, .proj-desc, .edu-desc, .club-desc {
    color: #4a5568;
    margin-top: 3px;
    text-align: left;
    white-space: pre-wrap;
  }
  .work-achievements {
    padding-left: 22px;
    margin-top: 4px;
    color: #4a5568;
  }
  .work-achievements li { margin-bottom: 2px; text-align: left; }

  /* ── 技能：标签化 ── */
  .skill-cat { margin-bottom: 6px; display: flex; flex-wrap: wrap; align-items: baseline; }
  .skill-name { font-weight: 600; color: #1a202c; min-width: 88px; }
  .skill-item {
    display: inline-block;
    background: rgba(37, 99, 235, 0.08);
    border: 1px solid rgba(37, 99, 235, 0.2);
    color: var(--accent-color);
    border-radius: 4px;
    padding: 1px 8px;
    margin: 2px 4px 2px 0;
    font-size: calc(var(--font-size) * 0.92);
  }

  .proj-tech { color: #718096; font-size: calc(var(--font-size) * 0.9); margin-top: 3px; }
  .lang-item, .cert-item, .honor-item, .rec-item { margin-bottom: 4px; color: #4a5568; }
  .honor-date, .rec-contact { color: #a0aec0; font-size: calc(var(--font-size) * 0.9); }
  .interests, .social-link, .fallback-row { color: #4a5568; }
  .fallback-row { margin-bottom: 3px; }
  .fallback-key { font-weight: 600; color: #1a202c; }

  /* ── 其他/自定义板块 ── */
  .other-title, .custom-title { font-weight: 600; color: #1a202c; margin-bottom: 3px; }
  .other-content, .custom-content { color: #4a5568; text-align: left; white-space: pre-wrap; }
  .pub-title { font-weight: 600; color: #1a202c; }
  .pub-authors { color: #4a5568; font-size: calc(var(--font-size) * 0.95); }
  .pub-info { color: #a0aec0; font-size: calc(var(--font-size) * 0.88); }

  /* ── 编辑器预览交互 ── */
  .module-interactive { cursor: pointer; transition: background-color 0.15s ease; border-radius: 4px; }
  .module-interactive:hover { background-color: rgba(37, 99, 235, 0.05); }
`;
