import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import MarkdownRenderer from "./MarkdownRenderer";

describe("MarkdownRenderer (Task 2.4)", () => {
  it("渲染段落文本", () => {
    render(<MarkdownRenderer>候选人精通 Python。</MarkdownRenderer>);
    expect(screen.getByText("候选人精通 Python。")).toBeInTheDocument();
  });

  it("渲染 H1/H2/H3 标题并附语义化标签", () => {
    render(
      <MarkdownRenderer>
        {"# 一级标题\n## 二级标题\n### 三级标题"}
      </MarkdownRenderer>
    );
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("一级标题");
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("二级标题");
    expect(screen.getByRole("heading", { level: 3 })).toHaveTextContent("三级标题");
  });

  it("渲染无序列表", () => {
    render(
      <MarkdownRenderer>
        {"- Python\n- FastAPI\n- MySQL"}
      </MarkdownRenderer>
    );
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(3);
    expect(screen.getByText("Python")).toBeInTheDocument();
    expect(screen.getByText("FastAPI")).toBeInTheDocument();
    expect(screen.getByText("MySQL")).toBeInTheDocument();
  });

  it("渲染有序列表", () => {
    render(
      <MarkdownRenderer>
        {"1. 第一项\n2. 第二项\n3. 第三项"}
      </MarkdownRenderer>
    );
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(3);
  });

  it("渲染加粗和行内代码", () => {
    render(
      <MarkdownRenderer>
        {"这是 **加粗** 文本，含 `inline code`。"}
      </MarkdownRenderer>
    );
    expect(screen.getByText("加粗").tagName).toBe("STRONG");
    expect(screen.getByText("inline code").tagName).toBe("CODE");
  });

  it("渲染代码块（fenced）", () => {
    render(
      <MarkdownRenderer>
        {"```python\nprint('hello')\n```"}
      </MarkdownRenderer>
    );
    const pre = document.querySelector("pre");
    expect(pre).not.toBeNull();
    expect(pre?.textContent).toContain("print('hello')");
  });

  it("GFM: 渲染表格", () => {
    render(
      <MarkdownRenderer>
        {
          "| 项目 | 分数 |\n| --- | --- |\n| ATS | 85 |\n| 关键词 | 80 |"
        }
      </MarkdownRenderer>
    );
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByText("ATS")).toBeInTheDocument();
    expect(screen.getByText("85")).toBeInTheDocument();
  });

  it("GFM: 渲染删除线（~~text~~）", () => {
    render(
      <MarkdownRenderer>
        {"这是 ~~删除~~ 文本"}
      </MarkdownRenderer>
    );
    expect(screen.getByText("删除").tagName).toBe("DEL");
  });

  it("remark-breaks: 单换行被渲染为 <br>（同段内换行不合并）", () => {
    render(
      <MarkdownRenderer>
        {"第一行\n第二行"}
      </MarkdownRenderer>
    );
    const brs = document.querySelectorAll("br");
    expect(brs.length).toBeGreaterThanOrEqual(1);
  });

  it("rehype-sanitize: 剥离 <script> 标签", () => {
    render(
      <MarkdownRenderer>
        {"文本前\n\n<script>alert('xss')</script>\n\n文本后"}
      </MarkdownRenderer>
    );
    const script = document.querySelector("script");
    expect(script).toBeNull();
    // script 内容不应被渲染为文本
    expect(screen.queryByText(/alert/)).toBeNull();
  });

  it("rehype-sanitize: raw HTML <img> 不被渲染为元素（默认安全）", () => {
    render(
      <MarkdownRenderer>
        {'<img src="x.png" onclick="alert(\'xss\')" alt="pic" />'}
      </MarkdownRenderer>
    );
    // react-markdown 默认不渲染 raw HTML，img 元素不应存在
    const img = document.querySelector("img");
    expect(img).toBeNull();
  });

  it("rehype-sanitize: 剥离 markdown 链接的 javascript: 协议", () => {
    render(
      <MarkdownRenderer>
        {"[危险链接](javascript:alert(1))"}
      </MarkdownRenderer>
    );
    // <a> 元素存在（由 markdown 语法生成），但 href 中的 javascript: 必须被剥离
    const link = document.querySelector("a");
    expect(link).not.toBeNull();
    const href = link?.getAttribute("href") ?? "";
    expect(href).not.toContain("javascript:");
  });

  it("自定义 className：H1 带 markdown-h1 class", () => {
    render(<MarkdownRenderer>{"# 标题"}</MarkdownRenderer>);
    const h1 = screen.getByRole("heading", { level: 1 });
    expect(h1.className).toContain("markdown-h1");
  });

  it("自定义 className：PRE 带 markdown-pre class", () => {
    render(<MarkdownRenderer>{"```python\ncode\n```"}</MarkdownRenderer>);
    const pre = document.querySelector("pre");
    expect(pre?.className).toContain("markdown-pre");
  });

  it("自定义 className：CODE（inline）带 markdown-code class", () => {
    render(<MarkdownRenderer>{"含 `inline` 代码"}</MarkdownRenderer>);
    const code = screen.getByText("inline");
    expect(code.className).toContain("markdown-code");
  });

  it("空内容渲染为空（不报错）", () => {
    const { container } = render(<MarkdownRenderer>{""}</MarkdownRenderer>);
    expect(container.firstChild).not.toBeNull();
  });

  it("职位推荐列表：列表项渲染为卡片样式", () => {
    render(
      <MarkdownRenderer>
        {"- **AI应用开发工程师**：您有 LLM 应用开发经验\n- **后端开发工程师**：具备 FastAPI 技能"}
      </MarkdownRenderer>
    );
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(2);
    // 验证列表项有卡片样式类名
    expect(items[0].className).toContain("markdown-li-card");
    expect(items[1].className).toContain("markdown-li-card");
  });

  it("职位推荐列表：strong 渲染为徽章样式", () => {
    render(
      <MarkdownRenderer>
        {"- **AI应用开发工程师**：描述文本"}
      </MarkdownRenderer>
    );
    const strong = screen.getByText("AI应用开发工程师");
    expect(strong.tagName).toBe("STRONG");
    expect(strong.className).toContain("markdown-strong-badge");
  });
});
