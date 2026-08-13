/**
 * 共享 Section 渲染组件 — 平移后端 services/resume_template.py 的 15 个渲染器。
 *
 * 每个 Section 输出与后端 _render_xxx 一致的 DOM 结构 + class 名，
 * 使前端 React 预览与后端 WeasyPrint PDF 导出视觉天然一致。
 * 样式由各模板通过 CSS 变量（--font-size/--accent-color 等）驱动。
 *
 * ## data-resume-item-index：条目级分页的测量锚点
 *
 * 列表型模块（教育/工作/项目/…）的每个条目 div 都带 `data-resume-item-index={i}`。
 * usePagination 的测量层据此拿到「section 固定开销（标题+内边距）+ 逐条目高度」，
 * packPages 才能在条目边界处断页，而不是把整个 section 整体挪到下一页 —— 后者
 * 会在上一页尾部留下大片空白（例如项目经历有 5 条，装不下就全部下移）。
 *
 * 没有这个属性的模块（basic_info / interests / social_links / other）视为不可拆分，
 * 仍按整块装箱。
 */

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkBreaks from "remark-breaks";
import rehypeSanitize from "rehype-sanitize";
import type { ModuleContent, ModuleType } from "../../../api/builder";

// ── 辅助函数（content 是宽松 dict，安全读取） ──────────────────

const str = (v: unknown): string => (typeof v === "string" ? v : "");

const safeHttpUrl = (v: unknown): string => {
  const raw = str(v).trim();
  if (!raw) return "";
  try {
    const parsed = new URL(raw);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? raw : "";
  } catch {
    return "";
  }
};

function ExternalLinkOrText({ value }: { value: unknown }) {
  const text = str(value);
  const href = safeHttpUrl(value);
  return href ? (
    <a href={href} target="_blank" rel="noopener noreferrer">{text}</a>
  ) : <>{text}</>;
}

/**
 * 长文本字段的 Markdown 渲染（对齐后端 resume_template._render_md）。
 *
 * Tiptap 上线后编辑器存的是 Markdown，预览需渲染为格式化 HTML 而非字面量标记。
 * - remark-breaks：单换行 → <br>（与后端 nl2br 扩展行为一致）
 * - rehype-sanitize：剥 XSS（react-markdown 默认不转义原始 HTML，必须净化）
 * - 组件映射只给列表/段落最小语义样式（list-style 对抗 Tailwind preflight），
 *   主体字号/颜色继承所在模板容器（.work-desc 等），不施加 React 侧固定字号。
 */
function Md({ children }: { children: string }) {
  if (!children) return null;
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkBreaks]}
      rehypePlugins={[rehypeSanitize]}
      components={{
        p: ({ node, ...props }) => <p className="my-0.5 first:mt-0 last:mb-0" {...props} />,
        ul: ({ node, ...props }) => <ul className="list-disc pl-5 my-0.5" {...props} />,
        ol: ({ node, ...props }) => <ol className="list-decimal pl-5 my-0.5" {...props} />,
        li: ({ node, ...props }) => <li className="my-0.5" {...props} />,
        a: ({ node, ...props }) => (
          <a className="underline underline-offset-2" {...props} />
        ),
      }}
    >
      {children}
    </ReactMarkdown>
  );
}

const strList = (v: unknown): string[] =>
  Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];

const dictList = (v: unknown): Array<Record<string, unknown>> =>
  Array.isArray(v)
    ? v.filter((x): x is Record<string, unknown> => !!x && typeof x === "object")
    : [];

/**
 * 条目列表：items 优先（后端 v2 / LLM 反解析产物统一用 items），兜底旧格式 entries。
 * 只读 entries 会让上传物化的简历列表模块在前端预览为空（模块字段不显示 bug 根因）。
 * 过滤 hidden 条目（编辑端 EyeSlash 隐藏的条目不渲染，修复"隐藏功能无法使用"）。
 */
const entryList = (content: ModuleContent): Array<Record<string, unknown>> =>
  dictList(
    (content as Record<string, unknown>).items ??
      (content as Record<string, unknown>).entries,
  ).filter((e) => !e.hidden);

const formatDateRange = (start?: unknown, end?: unknown): string => {
  const s = str(start);
  const e = str(end);
  if (s && e) return `${s} - ${e}`;
  if (s) return `${s} - 至今`;
  if (e) return e;
  return "";
};

// ── 条目切片（条目级分页） ────────────────────────────────────

/**
 * 条目区间 [start, end)。
 * 分页时同一个 section 可能被切成多段分布在连续页上，
 * 每页只渲染属于自己的那段条目。
 */
export interface ItemRange {
  start: number;
  end: number;
}

/**
 * 按区间切条目，同时保留**原始下标**。
 *
 * 保留原始下标很关键：`data-resume-item-index` 必须是全局稳定的编号，
 * 否则续页上的第 1 条会被标成 index 0，与测量层的编号对不上，装箱结果错位。
 */
function sliceRows<T>(rows: T[], range?: ItemRange): Array<[T, number]> {
  const pairs = rows.map((row, i) => [row, i] as [T, number]);
  if (!range) return pairs;
  return pairs.slice(range.start, range.end);
}

/** 列表型 Section 的统一 props */
interface ListSectionProps {
  content: ModuleContent;
  /** 只渲染该区间内的条目（不传 = 全部，用于测量层与非分页场景） */
  itemRange?: ItemRange;
}

// ── 模块标题映射（对齐后端 _MODULE_TITLES） ───────────────────

export const MODULE_TITLES: Record<string, string> = {
  basic_info: "个人简介",
  education: "教育背景",
  work_experience: "工作经历",
  project_experience: "项目经历",
  skills: "专业技能",
  language: "语言能力",
  honors: "荣誉奖项",
  certificates: "证书",
  interests: "兴趣爱好",
  club_activities: "社团活动",
  publications: "研究成果",
  recommendation: "推荐人",
  social_links: "社交链接",
  other: "其他",
  custom: "自定义",
};

// ── 各模块 Section ───────────────────────────────────────────

function SectionBasicInfo({ content }: { content: ModuleContent }) {
  const name = str(content.name);
  const avatar = str(content.avatar);
  const jobTitle = str(content.job_title);
  const phone = str(content.phone);
  const email = str(content.email);
  const location = str(content.location);
  const status = str(content.status);
  const hometown = str(content.hometown);
  const gender = str(content.gender);
  // age 是 number 类型（str() 只接受 string），需显式转字符串
  const age = content.age != null && content.age !== "" ? String(content.age) : "";
  const summary = str(content.summary);
  const profileLinks = [
    safeHttpUrl(content.github_url) ? { label: "GitHub", url: safeHttpUrl(content.github_url) } : null,
    safeHttpUrl(content.blog_url) ? { label: "博客", url: safeHttpUrl(content.blog_url) } : null,
    safeHttpUrl(content.homepage_url) ? { label: "主页", url: safeHttpUrl(content.homepage_url) } : null,
  ].filter((item): item is { label: string; url: string } => Boolean(item?.url));

  const contacts = [
    gender ? `性别: ${gender}` : "",
    age ? `年龄: ${age}` : "",
    phone,
    email,
    location,
    status,
    hometown ? `籍贯: ${hometown}` : "",
  ].filter(Boolean);

  return (
    <div className="basic-header">
      {(name || avatar) && (
        <div className="basic-header-line">
          {avatar && (
            <img className="basic-avatar" src={avatar} alt={name} width={80} height={80} />
          )}
          {name && <div className="basic-name">{name}</div>}
        </div>
      )}
      {jobTitle && <div className="basic-job-title">{jobTitle}</div>}
      {contacts.length > 0 && <div className="basic-contact">{contacts.join(" | ")}</div>}
      {profileLinks.length > 0 && (
        <div className="basic-links">
          {profileLinks.map((item, i) => (
            <span key={item.label}>
              <a href={item.url} target="_blank" rel="noopener noreferrer">{item.label}</a>
              {i < profileLinks.length - 1 ? " | " : ""}
            </span>
          ))}
        </div>
      )}
      {summary && <div className="basic-summary"><Md>{summary}</Md></div>}
      {dictList(content.custom_fields).filter((f) => str(f.key)).length > 0 && (
        <div className="basic-custom-fields">
          {dictList(content.custom_fields)
            .filter((f) => str(f.key))
            .map((f, i) => (
              <span key={i}>
                <b>{str(f.key)}</b>: {str(f.value)}
                {i > 0 ? "" : ""}
              </span>
            ))
            .reduce<React.ReactNode[]>((acc, node, i, arr) => {
              acc.push(node);
              if (i < arr.length - 1) acc.push(" | ");
              return acc;
            }, [])}
        </div>
      )}
    </div>
  );
}

function SectionEducation({ content, itemRange }: ListSectionProps) {
  const rows = sliceRows(entryList(content), itemRange);
  if (!rows.length) return null;
  return (
    <>
      {rows.map(([entry, i]) => {
        const info = [
          str(entry.degree),
          str(entry.major),
          entry.gpa !== undefined && entry.gpa !== "" ? `GPA: ${str(entry.gpa)}` : "",
        ].filter(Boolean);
        const dates = formatDateRange(entry.start_date, entry.end_date);
        return (
          <div key={i} className="edu-item" data-resume-item-index={i}>
            <div className="edu-header">
              <span className="edu-school">{str(entry.school)}</span>
              {dates && <span className="edu-date">{dates}</span>}
            </div>
            {info.length > 0 && <div className="edu-info">{info.join(" | ")}</div>}
            {str(entry.description) && <div className="edu-desc"><Md>{str(entry.description)}</Md></div>}
          </div>
        );
      })}
    </>
  );
}

function SectionWorkExperience({ content, itemRange }: ListSectionProps) {
  const rows = sliceRows(entryList(content), itemRange);
  if (!rows.length) return null;
  return (
    <>
      {rows.map(([entry, i]) => (
        <div key={i} className="work-item" data-resume-item-index={i}>
          <div className="work-header">
            <span className="work-company">{str(entry.company)}</span>
            {str(entry.position) && <span className="work-position">{str(entry.position)}</span>}
            {formatDateRange(entry.start_date, entry.end_date) && (
              <span className="work-date">{formatDateRange(entry.start_date, entry.end_date)}</span>
            )}
          </div>
          {str(entry.description) && <div className="work-desc"><Md>{str(entry.description)}</Md></div>}
          {strList(entry.achievements).length > 0 && (
            <ul className="work-achievements">
              {strList(entry.achievements).map((a, j) => (
                <li key={j}><Md>{a}</Md></li>
              ))}
            </ul>
          )}
        </div>
      ))}
    </>
  );
}

function SectionProjectExperience({ content, itemRange }: ListSectionProps) {
  const rows = sliceRows(entryList(content), itemRange);
  if (!rows.length) return null;
  return (
    <>
      {rows.map(([entry, i]) => {
        const desc = str(entry.description);
        const tech = strList(entry.tech_stack);
        const projectUrl = safeHttpUrl(entry.url);
        const displayUrl = projectUrl.replace(/^https?:\/\//, "").replace(/\/$/, "");
        // 去重：描述正文若已包含"技术栈"行，则不再单独渲染 proj-tech，避免重复
        const descHasTech = /技术栈\s*[:：]/.test(desc);
        return (
          <div key={i} className="proj-item" data-resume-item-index={i}>
            <div className="proj-header">
              <span className="proj-name">{str(entry.name)}</span>
              {str(entry.role) && <span className="proj-role">{str(entry.role)}</span>}
              {formatDateRange(entry.start_date, entry.end_date) && (
                <span className="proj-date">{formatDateRange(entry.start_date, entry.end_date)}</span>
              )}
            </div>
            {projectUrl && (
              <div className="proj-url">
                <a href={projectUrl} target="_blank" rel="noopener noreferrer">{displayUrl}</a>
              </div>
            )}
            {desc && <div className="proj-desc"><Md>{desc}</Md></div>}
            {tech.length > 0 && !descHasTech && (
              <div className="proj-tech">技术栈: {tech.join(", ")}</div>
            )}
          </div>
        );
      })}
    </>
  );
}

function SectionSkills({ content, itemRange }: ListSectionProps) {
  // 优先新格式 items（含 level/category），fallback 旧格式 categories
  const newItems = dictList(content.items);
  const hasNew = newItems.length > 0;

  // 统一成「分类 → [{name, level}]」结构
  const grouped: Array<{ name: string; skills: Array<{ name: string; level?: number }> }> = [];
  if (hasNew) {
    const byCat = new Map<string, Array<{ name: string; level?: number }>>();
    for (const item of newItems) {
      const name = str(item.name);
      if (!name) continue;
      const cat = str(item.category) || "其他";
      const level = typeof item.level === "number" ? item.level : undefined;
      const list = byCat.get(cat) ?? [];
      list.push({ name, level });
      byCat.set(cat, list);
    }
    for (const [catName, skills] of byCat) grouped.push({ name: catName, skills });
  } else {
    const cats = dictList(content.categories).filter((c) => strList(c.items).length > 0);
    for (const cat of cats) {
      grouped.push({
        name: str(cat.name),
        skills: strList(cat.items).map((name) => ({ name })),
      });
    }
  }

  const rows = sliceRows(grouped, itemRange);
  if (!rows.length) return null;

  return (
    <>
      {rows.map(([cat, i]) => (
        <div key={i} className="skill-cat" data-resume-item-index={i}>
          <span className="skill-name">{str(cat.name)}</span>{" "}
          {cat.skills.map((skill, j) => {
            // 熟练度：数据里有 level 就渲染进度条（不再依赖 show_levels 开关，修复"熟练度不显示"）
            const level = typeof skill.level === "number" ? skill.level : null;
            const pct = level != null ? `${Math.min(100, Math.max(0, (level / 5) * 100))}%` : null;
            return (
              <span key={j} className="skill-item">
                {skill.name}
                {pct != null && (
                  <span
                    className="skill-level-bar"
                    style={{
                      display: "inline-flex",
                      width: "2.6em",
                      height: "4px",
                      marginLeft: "4px",
                      borderRadius: "999px",
                      background: "rgba(0,0,0,0.08)",
                      overflow: "hidden",
                      verticalAlign: "middle",
                    }}
                  >
                    <span
                      style={{
                        width: pct,
                        height: "100%",
                        borderRadius: "999px",
                        background: "var(--accent-color)",
                      }}
                    />
                  </span>
                )}
              </span>
            );
          })}
        </div>
      ))}
    </>
  );
}

function SectionLanguage({ content, itemRange }: ListSectionProps) {
  const rows = sliceRows(entryList(content), itemRange);
  if (!rows.length) return null;
  return (
    <>
      {rows.map(([entry, i]) => {
        const parts = [
          <strong key="n">{str(entry.name)}</strong>,
          ...(str(entry.proficiency) ? [str(entry.proficiency)] : []),
          ...(str(entry.score) ? [str(entry.score)] : []),
        ];
        return (
          <div key={i} className="lang-item" data-resume-item-index={i}>
            {parts.map((p, j) => (
              <span key={j}>{j > 0 ? " - " : ""}{p}</span>
            ))}
          </div>
        );
      })}
    </>
  );
}

function SectionHonors({ content, itemRange }: ListSectionProps) {
  const rows = sliceRows(entryList(content), itemRange);
  if (!rows.length) return null;
  return (
    <>
      {rows.map(([entry, i]) => (
        <div key={i} className="honor-item" data-resume-item-index={i}>
          <span className="honor-title">{str(entry.title)}</span>
          {str(entry.date) && <span className="honor-date">{str(entry.date)}</span>}
          {str(entry.description) && <div className="honor-desc"><Md>{str(entry.description)}</Md></div>}
        </div>
      ))}
    </>
  );
}

function SectionCertificates({ content, itemRange }: ListSectionProps) {
  const rows = sliceRows(entryList(content), itemRange);
  if (!rows.length) return null;
  return (
    <>
      {rows.map(([entry, i]) => {
        const parts = [
          <strong key="n">{str(entry.name)}</strong>,
          ...(str(entry.issuer) ? [str(entry.issuer)] : []),
          ...(str(entry.date) ? [str(entry.date)] : []),
          ...(str(entry.score) ? [`成绩: ${str(entry.score)}`] : []),
        ];
        return (
          <div key={i} className="cert-item" data-resume-item-index={i}>
            {parts.map((p, j) => (
              <span key={j}>{j > 0 ? " - " : ""}{p}</span>
            ))}
          </div>
        );
      })}
    </>
  );
}

function SectionInterests({ content }: { content: ModuleContent }) {
  const items = strList(content.items);
  if (!items.length) return null;
  return <div className="interests">{items.join(", ")}</div>;
}

function SectionClubActivities({ content, itemRange }: ListSectionProps) {
  const rows = sliceRows(entryList(content), itemRange);
  if (!rows.length) return null;
  return (
    <>
      {rows.map(([entry, i]) => (
        <div key={i} className="club-item" data-resume-item-index={i}>
          <span className="club-name">{str(entry.name)}</span>
          {str(entry.role) && <span className="club-role">{str(entry.role)}</span>}
          {formatDateRange(entry.start_date, entry.end_date) && (
            <span className="club-date">{formatDateRange(entry.start_date, entry.end_date)}</span>
          )}
          {str(entry.description) && <div className="club-desc"><Md>{str(entry.description)}</Md></div>}
        </div>
      ))}
    </>
  );
}

function SectionPublications({ content, itemRange }: ListSectionProps) {
  const rows = sliceRows(entryList(content), itemRange);
  if (!rows.length) return null;
  return (
    <>
      {rows.map(([entry, i]) => {
        const info = [str(entry.venue), str(entry.date)].filter(Boolean);
        return (
          <div key={i} className="pub-item" data-resume-item-index={i}>
            <div className="pub-title">{str(entry.title)}</div>
            {strList(entry.authors).length > 0 && (
              <div className="pub-authors">{strList(entry.authors).join(", ")}</div>
            )}
            {info.length > 0 && <div className="pub-info">{info.join(" - ")}</div>}
            {safeHttpUrl(entry.url) && (
              <div className="pub-url">
                <a href={safeHttpUrl(entry.url)} target="_blank" rel="noopener noreferrer">
                  {str(entry.url)}
                </a>
              </div>
            )}
          </div>
        );
      })}
    </>
  );
}

function SectionRecommendation({ content, itemRange }: ListSectionProps) {
  const rows = sliceRows(entryList(content), itemRange);
  if (!rows.length) return null;
  return (
    <>
      {rows.map(([entry, i]) => {
        const parts = [
          <strong key="n">{str(entry.name)}</strong>,
          ...(str(entry.title) ? [str(entry.title)] : []),
          ...(str(entry.organization) ? [str(entry.organization)] : []),
        ];
        const contact = [str(entry.contact), str(entry.email)].filter(Boolean);
        return (
          <div key={i} className="rec-item" data-resume-item-index={i}>
            <span>
              {parts.map((p, j) => (
                <span key={j}>{j > 0 ? " - " : ""}{p}</span>
              ))}
            </span>
            {contact.length > 0 && <div className="rec-contact">{contact.join(" | ")}</div>}
          </div>
        );
      })}
    </>
  );
}

function SectionSocialLinks({ content }: { content: ModuleContent }) {
  const fields: Array<[string, string]> = [
    ["github", "GitHub"],
    ["linkedin", "LinkedIn"],
    ["website", "个人网站"],
    ["twitter", "Twitter"],
    ["wechat", "微信"],
  ];
  const parts = fields
    .filter(([key]) => str(content[key]))
    .map(([key, label]) => (
      <span key={key} className="social-link">
        <strong>{label}</strong>: <ExternalLinkOrText value={content[key]} />
      </span>
    ));
  for (const other of dictList(content.others)) {
    const name = str(other.name);
    const url = str(other.url);
    if (name || url) {
      parts.push(
        <span key={`o-${parts.length}`} className="social-link">
          <strong>{name}</strong>: <ExternalLinkOrText value={url} />
        </span>,
      );
    }
  }
  // v2: items 优先（后端存 items: [{name,url}] 或 [{label,value}]），兜底旧固定字段
  for (const it of dictList((content as Record<string, unknown>).items)) {
    const name = str(it.name) || str(it.label);
    const url = str(it.url) || str(it.value);
    if (name || url) {
      parts.push(
        <span key={`i-${parts.length}`} className="social-link">
          <strong>{name}</strong>: <ExternalLinkOrText value={url} />
        </span>,
      );
    }
  }
  if (!parts.length) return null;
  return (
    <div className="social-links">
      {parts.map((p, i) => (
        <span key={i}>{i > 0 ? " | " : ""}{p}</span>
      ))}
    </div>
  );
}

function SectionOther({ content }: { content: ModuleContent }) {
  const text = str(content.content);
  if (!text) return null;
  return (
    <>
      {str(content.title) && <div className="other-title">{str(content.title)}</div>}
      <div className="other-content"><Md>{text}</Md></div>
    </>
  );
}

function SectionCustom({ content }: { content: ModuleContent }) {
  // 多板块模式（entries）
  const entries = entryList(content).filter((e) => str(e.content));
  if (entries.length > 0) {
    return (
      <>
        {entries.map((entry, i) => (
          <div key={i}>
            {str(entry.title) && <div className="custom-title">{str(entry.title)}</div>}
            <div className="custom-content"><Md>{str(entry.content)}</Md></div>
          </div>
        ))}
      </>
    );
  }
  // 向后兼容单板块模式
  const text = str(content.content);
  if (!text) return null;
  return (
    <>
      {str(content.title) && <div className="custom-title">{str(content.title)}</div>}
      <div className="custom-content"><Md>{text}</Md></div>
    </>
  );
}

function SectionFallback({ content }: { content: ModuleContent }) {
  const rows = Object.entries(content).filter(
    ([, v]) => v !== null && v !== "" && !(Array.isArray(v) && v.length === 0),
  );
  if (!rows.length) return null;
  return (
    <>
      {rows.map(([k, v]) => (
        <div key={k} className="fallback-row">
          <span className="fallback-key">{k}</span>:{" "}
          {Array.isArray(v) ? v.join(", ") : String(v)}
        </div>
      ))}
    </>
  );
}

// ── 分发器（对齐后端 _MODULE_RENDERERS 映射） ─────────────────

export function SectionContent({
  moduleType,
  content,
  itemRange,
}: {
  moduleType: ModuleType;
  content: ModuleContent;
  /** 条目级分页：只渲染 [start, end) 区间条目；不传 = 全部（测量层/非分页场景） */
  itemRange?: ItemRange;
}) {
  switch (moduleType) {
    case "basic_info":
      return <SectionBasicInfo content={content} />;
    case "education":
      return <SectionEducation content={content} itemRange={itemRange} />;
    case "work_experience":
      return <SectionWorkExperience content={content} itemRange={itemRange} />;
    case "project_experience":
      return <SectionProjectExperience content={content} itemRange={itemRange} />;
    case "skills":
      return <SectionSkills content={content} itemRange={itemRange} />;
    case "language":
      return <SectionLanguage content={content} itemRange={itemRange} />;
    case "honors":
      return <SectionHonors content={content} itemRange={itemRange} />;
    case "certificates":
      return <SectionCertificates content={content} itemRange={itemRange} />;
    case "interests":
      return <SectionInterests content={content} />;
    case "club_activities":
      return <SectionClubActivities content={content} itemRange={itemRange} />;
    case "publications":
      return <SectionPublications content={content} itemRange={itemRange} />;
    case "recommendation":
      return <SectionRecommendation content={content} itemRange={itemRange} />;
    case "social_links":
      return <SectionSocialLinks content={content} />;
    case "other":
      return <SectionOther content={content} />;
    case "custom":
      return <SectionCustom content={content} />;
    default:
      return <SectionFallback content={content} />;
  }
}
