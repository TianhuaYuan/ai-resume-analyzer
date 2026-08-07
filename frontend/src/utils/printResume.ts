/**
 * printResume — 浏览器打印导出。
 *
 * ## 为什么不能直接克隆预览 DOM
 *
 * 预览区已改为「真实多页容器」：每页是独立的 A4 div，带 `gap`、`shadow`、页码 `figcaption`，
 * 且每页内部有 `transform: scale(zoom)` 视口缩放。直接克隆会导致：
 * - 页间 gap 被算进页高，累积后分页整体下移
 * - figcaption 页码被打印出来
 * - transform 不参与布局，浏览器分页时无视它 → 分页位置错乱
 *
 * ## 本实现：重新生成单长 DOM 交给 @page
 *
 * 从预览区提取全部 section 节点，按顺序拼成一条连续 DOM，
 * 每个 section 加 `break-inside: avoid` 让浏览器自己在合适位置断页。
 * 这样打印引擎的分页决策与预览的装箱结果高度一致（两者都遵守「section 不拆开」）。
 *
 * ## transform → zoom 转换（借鉴 magic-resume print.ts）
 *
 * 自动压缩用的是 `transform: scale()`，但 `transform` **不参与布局计算**，
 * 浏览器分页时会完全无视它，导致压缩后打印仍是原来的页数。
 * `zoom` 参与布局，所以打印前必须把 scale 换算成 zoom。
 */

const A4_WIDTH_PX = 210 * (96 / 25.4); // 793.70
const A4_HEIGHT_PX = 297 * (96 / 25.4); // 1122.52

export async function exportResumeToBrowserPrint(options?: {
  title?: string;
}): Promise<void> {
  const source = document.getElementById("resume-preview");
  if (!source) {
    throw new Error("简历预览不存在");
  }

  const title = options?.title || "简历";

  // ── 1. 收集模板 <style>（每个模板组件内联的 CSS） ──
  const styles = Array.from(source.querySelectorAll("style"))
    .map((s) => s.textContent)
    .filter(Boolean)
    .join("\n");

  // ── 2. 提取自动压缩的 scale（用于换算 zoom） ──
  // PaginatedResumePreview 的内容压缩层带 transform: scale(x)，x < 1 时生效
  let contentScale = 1;
  const scaledEl = source.querySelector<HTMLElement>(
    ".a4-preview-scale-wrapper > div[style*='scale']",
  );
  if (scaledEl) {
    const m = scaledEl.style.transform.match(/scale\(([\d.]+)\)/);
    if (m) {
      const v = parseFloat(m[1]);
      if (Number.isFinite(v) && v > 0 && v < 1) contentScale = v;
    }
  }

  // ── 3. 取第一页的 resume-template-root 作为结构模板，把所有 section 汇总进去 ──
  // 多页容器里每页都有一个 resume-template-root（含相同的模板 class 与 CSS 变量），
  // 取首页作为壳，再把各页的 section 依次搬进来，还原成完整的单条内容。
  const firstRoot = source.querySelector<HTMLElement>(".resume-template-root");
  if (!firstRoot) {
    throw new Error("简历内容为空");
  }

  const shell = firstRoot.cloneNode(false) as HTMLElement; // 只克隆自身（保留 CSS 变量 inline style）
  const templateEl = firstRoot.querySelector<HTMLElement>(".resume-template");
  if (!templateEl) {
    throw new Error("简历模板结构异常");
  }
  const templateShell = templateEl.cloneNode(false) as HTMLElement;
  const containerEl = templateEl.querySelector<HTMLElement>(".resume-container");
  const containerShell = (containerEl?.cloneNode(false) as HTMLElement) ?? document.createElement("div");
  if (!containerEl) containerShell.className = "resume-container";

  // 汇总所有页的 section，按 moduleType 合并条目。
  // 条目级分页后同一 section 分散在连续页（每页只含部分条目、续页无标题），
  // 简单去重会丢续页条目 —— 改为把各页的 [data-resume-item-index] 合并到第一个节点，
  // 生成每个 section 标题一次 + 全部条目按全局下标排序的完整单长 DOM。
  const nodesByType = new Map<string, HTMLElement[]>();
  source.querySelectorAll<HTMLElement>("[data-resume-section-id]").forEach((node) => {
    const id = node.dataset.resumeSectionId ?? "";
    if (!id) return;
    const list = nodesByType.get(id);
    if (list) list.push(node);
    else nodesByType.set(id, [node]);
  });
  for (const nodes of nodesByType.values()) {
    const main = nodes[0].cloneNode(true) as HTMLElement;
    main.classList.remove("module-interactive");
    const content = main.querySelector<HTMLElement>(".module-content");
    if (content) {
      content.querySelectorAll<HTMLElement>("[data-resume-item-index]").forEach((el) => el.remove());
      const allItems = nodes
        .flatMap((n) => Array.from(n.querySelectorAll<HTMLElement>("[data-resume-item-index]")))
        .sort(
          (a, b) =>
            (Number(a.dataset.resumeItemIndex) || 0) - (Number(b.dataset.resumeItemIndex) || 0),
        );
      for (const el of allItems) content.appendChild(el.cloneNode(true));
    }
    containerShell.appendChild(main);
  }

  templateShell.appendChild(containerShell);
  shell.appendChild(templateShell);

  // 自动压缩：transform → zoom（zoom 参与布局，分页才准确）
  if (contentScale < 1) {
    shell.style.zoom = String(contentScale);
  }
  shell.style.width = `${A4_WIDTH_PX}px`;

  const html = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>${title}</title>
<style>
  @page { size: A4; margin: 0; }
  html, body { margin: 0; padding: 0; background: #fff; }
  .resume-template-root { min-height: ${A4_HEIGHT_PX}px; background: #fff; }
  /* 让浏览器在 section 边界断页，与预览的装箱规则保持一致 */
  .resume-template [data-resume-section-id] {
    break-inside: avoid;
    page-break-inside: avoid;
    box-decoration-break: clone;
  }
  ${styles}
</style>
</head>
<body>
${shell.outerHTML}
</body>
</html>`;

  const iframe = document.createElement("iframe");
  iframe.style.position = "fixed";
  iframe.style.right = "0";
  iframe.style.bottom = "0";
  iframe.style.width = "0";
  iframe.style.height = "0";
  iframe.style.border = "0";
  iframe.setAttribute("aria-hidden", "true");
  document.body.appendChild(iframe);

  const iframeDoc = iframe.contentDocument;
  if (!iframeDoc || !iframe.contentWindow) {
    iframe.remove();
    throw new Error("无法创建打印窗口");
  }

  iframeDoc.open();
  iframeDoc.write(html);
  iframeDoc.close();

  // 等样式与字体就绪 + 双 rAF 缓冲
  await new Promise<void>((resolve) => {
    if (iframeDoc.fonts?.ready) {
      iframeDoc.fonts.ready.then(() => resolve());
    } else {
      resolve();
    }
  });
  await new Promise<void>((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
  });

  iframe.contentWindow.focus();
  iframe.contentWindow.print();

  setTimeout(() => {
    iframe.remove();
  }, 1000);
}
