/**
 * AICapabilitiesPage — AI 能力目录页（F「AI 能力呈现」）。
 *
 * 后端 Agent 的常用工具此前只藏在 /qa 对话里。本页把它们按用途分组
 * 以卡片形式集中呈现：每张卡片展示 图标 + 工具名 + 中文描述 + 触发问题，
 * 点击后 navigate("/qa", { state: { question } })（照抄 FloatingAIPanel 的
 * 跳转方式），由 QAPage 通过 location.state.question 自动预填触发。
 *
 * 分组（对应后端 TOOL_REGISTRY unified 19 工具）：
 *   - 诊断分析 / 岗位匹配 / 简历创作 / 面试辅导 / 知识检索 / 记忆
 */

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAppChat } from "../context/AppChatContext";
import Modal from "../components/ui/Modal";
import { BriefcaseMedical, Scale, CircleCheck, Crosshair, Briefcase, FileText, FilePlus, Type, Languages, Pencil, CircleHelp, Mic, Search, FolderOpen, Globe, HandCoins, Library, FileUser, MessageSquareText, Bookmark, History, ArrowRight, SendHorizontal } from "lucide-react";

interface CapabilityCard {
  /** 后端工具名（TOOL_REGISTRY 中的 name） */
  tool: string;
  /** 中文能力名 */
  name: string;
  /** 中文描述 */
  desc: string;
  /** Phosphor 图标组件 */
  icon: typeof FileText;
  /** 点击后预填到 /qa 的触发问题 */
  question: string;
}

interface CapabilityGroup {
  title: string;
  subtitle: string;
  cards: CapabilityCard[];
}

interface TaskField {
  key: string;
  label: string;
  placeholder?: string;
  type?: "text" | "textarea" | "select";
  required?: boolean;
  options?: Array<{ value: string; label: string }>;
  defaultValue?: string;
}

interface CapabilityFormConfig {
  title: string;
  description: string;
  fields: TaskField[];
  buildQuestion: (values: Record<string, string>) => string;
}

const MODULE_OPTIONS = [
  { value: "basic_info", label: "基本信息" },
  { value: "education", label: "教育经历" },
  { value: "work_experience", label: "工作 / 实习经历" },
  { value: "project_experience", label: "项目经历" },
  { value: "skills", label: "专业技能" },
  { value: "honors", label: "荣誉奖项" },
];

const MODULE_LABELS = Object.fromEntries(
  MODULE_OPTIONS.map(({ value, label }) => [value, label]),
) as Record<string, string>;

const moduleLabel = (value: string) => MODULE_LABELS[value] ?? value;

/**
 * 固定参数由界面收集，不浪费一次模型调用做“请提供 JD / 请选择模块”这类确定性追问。
 * 提交后仍进入同一对话，保留 Agent 的工具校验、审批和差异审阅链路。
 */
const CAPABILITY_FORMS: Record<string, CapabilityFormConfig> = {
  check_module: {
    title: "检查简历条目",
    description: "选择要检查的模块。系统只给出问题和建议，不会修改简历。",
    fields: [{ key: "module", label: "简历模块", type: "select", options: MODULE_OPTIONS, required: true, defaultValue: "work_experience" }],
    buildQuestion: ({ module }) => `检查当前简历的${moduleLabel(module)}，重点看完整性、表达质量和 ATS 兼容性，不要修改内容。`,
  },
  jd_match: {
    title: "岗位匹配",
    description: "粘贴完整岗位描述，结果会区分已满足、证据不足和明确缺口。",
    fields: [{ key: "jd", label: "岗位描述（JD）", type: "textarea", placeholder: "粘贴岗位职责、任职要求和加分项", required: true }],
    buildQuestion: ({ jd }) => `分析当前简历与以下岗位描述的匹配度和差距，并引用简历证据：\n\n${jd}`,
  },
  search_jobs_live: {
    title: "搜索岗位",
    description: "填写求职目标后再联网搜索，避免返回泛化岗位。",
    fields: [
      { key: "role", label: "目标职位", placeholder: "例如：Java 后端开发", required: true },
      { key: "city", label: "城市", placeholder: "例如：杭州", required: true },
      { key: "type", label: "招聘类型", type: "select", required: true, defaultValue: "校招", options: [
        { value: "校招", label: "校招" }, { value: "实习", label: "实习" }, { value: "社招", label: "社招" },
      ] },
    ],
    buildQuestion: ({ role, city, type }) => `实时搜索 ${city} 的 ${role} ${type}岗位，给出来源、发布时间和申请建议。`,
  },
  web_search: {
    title: "联网搜索",
    description: "搜索面经、薪资、公司评价或招聘信息。",
    fields: [{ key: "query", label: "搜索内容", placeholder: "例如：2026 字节跳动 Java 后端校招面经", required: true }],
    buildQuestion: ({ query }) => `联网搜索：${query}。请注明信息来源和时效。`,
  },
  rewrite_resume: {
    title: "整份生成或优化",
    description: "先限定目标和事实边界。写入前仍会要求确认并展示差异。",
    fields: [
      { key: "mode", label: "任务", type: "select", required: true, defaultValue: "优化现有简历", options: [
        { value: "优化现有简历", label: "优化现有简历" }, { value: "生成新简历", label: "生成新简历" },
      ] },
      { key: "role", label: "目标岗位", placeholder: "例如：Java 后端开发", required: true },
      { key: "scope", label: "修改范围与必须保留的事实", type: "textarea", placeholder: "例如：只优化项目和实习描述；不得新增技术栈", required: true },
    ],
    buildQuestion: ({ mode, role, scope }) => `${mode}，目标岗位是 ${role}。范围与事实约束：${scope}。先复述修改范围，得到确认后再写入。`,
  },
  generate_module: {
    title: "生成简历模块",
    description: "只生成一个模块，所有事实必须来自你提供的内容。",
    fields: [
      { key: "module", label: "目标模块", type: "select", options: MODULE_OPTIONS, required: true, defaultValue: "project_experience" },
      { key: "facts", label: "已确认事实", type: "textarea", placeholder: "提供名称、时间、职责、行动、结果和技术栈", required: true },
    ],
    buildQuestion: ({ module, facts }) => `仅为当前简历生成${moduleLabel(module)}。可用事实：${facts}。不得补充未提供的信息，写入前先让我确认。`,
  },
  rewrite_star: {
    title: "STAR 改写",
    description: "选择经历类型并说明目标；不得虚构结果数据。",
    fields: [
      { key: "module", label: "经历类型", type: "select", required: true, defaultValue: "project_experience", options: MODULE_OPTIONS.filter((item) => ["work_experience", "project_experience"].includes(item.value)) },
      { key: "role", label: "目标岗位", placeholder: "例如：Java 后端开发", required: true },
    ],
    buildQuestion: ({ module, role }) => `用 STAR 结构改写当前简历的${moduleLabel(module)}描述，目标岗位为 ${role}。保留全部事实，不得虚构量化结果，写入前先确认。`,
  },
  modify_module: {
    title: "定向修改",
    description: "明确模块和修改目标，避免误改其他内容。",
    fields: [
      { key: "module", label: "目标模块", type: "select", options: MODULE_OPTIONS, required: true, defaultValue: "project_experience" },
      { key: "instruction", label: "修改要求", type: "textarea", placeholder: "例如：压缩到 3 条，每条保留量化结果，不新增事实", required: true },
    ],
    buildQuestion: ({ module, instruction }) => `只修改当前简历的${moduleLabel(module)}。要求：${instruction}。不要改动其他模块，写入前先确认。`,
  },
  translate: {
    title: "翻译简历",
    description: "生成独立语言版本，原简历保持不变。",
    fields: [{ key: "language", label: "目标语言", type: "select", required: true, defaultValue: "英文", options: [
      { value: "英文", label: "英文" }, { value: "日文", label: "日文" }, { value: "韩文", label: "韩文" }, { value: "法文", label: "法文" }, { value: "德文", label: "德文" },
    ] }],
    buildQuestion: ({ language }) => `把当前简历翻译成${language}，保持字段结构和事实不变，创建独立语言版本，写入前先确认。`,
  },
  cover_letter: {
    title: "生成求职信",
    description: "求职信会结合当前简历证据和目标岗位。",
    fields: [
      { key: "recipient", label: "称呼", placeholder: "例如：招聘经理 / XX 公司招聘团队", required: true },
      { key: "jd", label: "岗位描述（JD）", type: "textarea", placeholder: "粘贴目标岗位描述", required: true },
    ],
    buildQuestion: ({ recipient, jd }) => `面向“${recipient}”写一封求职信，必须基于当前简历中的真实证据，并匹配以下 JD：\n\n${jd}`,
  },
  interview_coach: {
    title: "开始模拟面试",
    description: "确认场景后逐题进行，不会一次性倾倒全部题目。",
    fields: [
      { key: "role", label: "目标岗位", placeholder: "例如：Java 后端开发", required: true },
      { key: "type", label: "面试类型", type: "select", required: true, defaultValue: "技术面", options: [
        { value: "技术面", label: "技术面" }, { value: "项目面", label: "项目面" }, { value: "HR 面", label: "HR 面" },
      ] },
      { key: "difficulty", label: "难度", type: "select", required: true, defaultValue: "中等", options: [
        { value: "基础", label: "基础" }, { value: "中等", label: "中等" }, { value: "进阶", label: "进阶" },
      ] },
    ],
    buildQuestion: ({ role, type, difficulty }) => `开始 ${role} 的${type}模拟面试，难度${difficulty}。每次只问一题，等待我回答后再追问或进入下一题。`,
  },
  negotiation_brief: {
    title: "生成谈薪简报",
    description: "市场数据具有时效性，结果应给出来源与区间。",
    fields: [
      { key: "role", label: "目标岗位", placeholder: "例如：Java 后端开发", required: true },
      { key: "city", label: "城市", placeholder: "例如：杭州", required: true },
      { key: "years", label: "工作年限", placeholder: "例如：应届 / 0 年", required: true },
      { key: "current", label: "当前薪资（可选）", placeholder: "可留空" },
    ],
    buildQuestion: ({ role, city, years, current }) => `生成 ${city} ${role}（${years}）的谈薪简报${current ? `，当前薪资为 ${current}` : ""}，给出市场区间、证据来源、底线和沟通话术。`,
  },
  search_resume: {
    title: "检索当前简历",
    description: "定位具体内容并返回来源段落。",
    fields: [{ key: "query", label: "要查找的内容", placeholder: "例如：性能优化和量化结果", required: true }],
    buildQuestion: ({ query }) => `在当前简历中检索“${query}”，返回对应段落和所在模块。`,
  },
  search_assets: {
    title: "检索知识资产",
    description: "跨简历、岗位描述、面试记录和个人资料查找。",
    fields: [{ key: "query", label: "要查找的主题", placeholder: "例如：Redis 项目证据", required: true }],
    buildQuestion: ({ query }) => `跨我的知识资产检索“${query}”，按资产类型列出来源。`,
  },
  search_corpus: {
    title: "检索面经知识库",
    description: "查询离线面经、真题和范文库。",
    fields: [{ key: "query", label: "检索主题", placeholder: "例如：Java 并发和 Redis 高频题", required: true }],
    buildQuestion: ({ query }) => `检索面经知识库中的“${query}”，按主题整理并标出来源。`,
  },
  answer_from_index: {
    title: "深度问答",
    description: "对指定资料做检索、重排和证据化回答。",
    fields: [
      { key: "question", label: "具体问题", type: "textarea", placeholder: "例如：这个项目如何证明我的工程能力？", required: true },
      { key: "scope", label: "资料范围", type: "select", required: true, defaultValue: "当前简历", options: [
        { value: "当前简历", label: "当前简历" }, { value: "全部知识资产", label: "全部知识资产" }, { value: "面经知识库", label: "面经知识库" },
      ] },
    ],
    buildQuestion: ({ question, scope }) => `基于${scope}做有依据的深度回答：${question}。结论必须附来源，证据不足时明确说明。`,
  },
  save_memory: {
    title: "保存求职偏好",
    description: "只保存长期有用的目标或决定，不保存敏感凭据。",
    fields: [
      { key: "content", label: "要记住的内容", placeholder: "例如：优先杭州的后端校招岗位", required: true },
      { key: "scope", label: "适用范围", type: "select", required: true, defaultValue: "长期求职偏好", options: [
        { value: "长期求职偏好", label: "长期求职偏好" }, { value: "当前求职阶段", label: "当前求职阶段" },
      ] },
    ],
    buildQuestion: ({ content, scope }) => `请记住这项${scope}：${content}。保存后复述你记录的内容。`,
  },
  recall_memory: {
    title: "回忆求职偏好",
    description: "按主题查找之前保存的目标和决定。",
    fields: [{ key: "query", label: "回忆主题", placeholder: "例如：目标城市和岗位方向", required: true }],
    buildQuestion: ({ query }) => `回忆我们之前保存的“${query}”相关内容；没有记录时直接说明。`,
  },
};

/* ── 能力分组（覆盖后端 21 个工具） ── */

const CAPABILITY_GROUPS: CapabilityGroup[] = [
  {
    title: "诊断分析",
    subtitle: "先看清简历问题，再动手改",
    cards: [
      {
        tool: "diagnose_resume",
        name: "简历诊断",
        desc: "从招聘者视角诊断简历的完整性与质量，给出改进建议",
        icon: BriefcaseMedical,
        question: "帮我诊断这份简历的完整性和质量，给出改进建议",
      },
      {
        tool: "compare_resumes",
        name: "简历对比",
        desc: "横向对比多份简历的优劣势，给出综合裁决",
        icon: Scale,
        // __COMPARE__ 特殊指令：QAPage 收到后弹出「多选简历」选择器
        // （而不是让 Agent 要求用户输入简历 id —— 用户反馈不符合使用逻辑）
        question: "__COMPARE__",
      },
      {
        tool: "check_module",
        name: "条目检查",
        desc: "选择一个具体模块，检查完整性、表达和 ATS 兼容性，不修改内容",
        icon: CircleCheck,
        question: "我想检查一个具体简历模块。请先列出当前可检查的模块让我选择，不要修改内容。",
      },
      {
        tool: "ask_info",
        name: "信息追问",
        desc: "分析简历缺失项，提醒你还差哪些信息需要补充",
        icon: CircleHelp,
        question: "根据简历现状，帮我梳理还需要补充哪些信息",
      },
    ],
  },
  {
    title: "岗位匹配",
    subtitle: "知道该投什么，投得更准",
    cards: [
      {
        tool: "jd_match",
        name: "JD 匹配",
        desc: "把简历和目标岗位描述（JD）做匹配，分析匹配度与差距",
        icon: Crosshair,
        question: "我想做岗位匹配。请先让我粘贴目标岗位 JD，收到后再分析匹配度和差距。",
      },
      {
        tool: "search_jobs_live",
        name: "岗位推荐",
        desc: "实时搜索匹配的校招 / 社招 / 实习岗位",
        icon: Briefcase,
        question: "我想搜索岗位。请先询问目标职位、城市和校招/社招/实习类型，再开始搜索。",
      },
      {
        tool: "web_search",
        name: "联网搜索",
        desc: "实时搜索面经 / 薪资 / 公司评价等信息，弥补离线知识库的时效性缺口",
        icon: Globe,
        question: "搜索一下最近的 AI 岗位面经",
      },
    ],
  },
  {
    title: "简历创作",
    subtitle: "从零到一，改到最好",
    cards: [
      {
        tool: "rewrite_resume",
        name: "整份生成或优化",
        desc: "先确认目标岗位和事实信息，再生成空简历或优化现有内容",
        icon: FileText,
        question: "我想生成或优化整份简历。请先确认目标岗位、现有事实和修改范围，得到我确认后再写入。",
      },
      {
        tool: "generate_module",
        name: "模块生成",
        desc: "根据已确认事实生成指定模块内容，确认后写入简历",
        icon: FilePlus,
        question: "我想生成一个简历模块。请先列出可生成的模块让我选择，并逐项确认事实后再写入。",
      },
      {
        tool: "rewrite_star",
        name: "STAR 改写",
        desc: "用 STAR 法则改写经历描述，让表达更专业、更有说服力",
        icon: Type,
        question: "我想用 STAR 法则改写一段经历。请先列出可改写的经历让我选择，确认后再写入。",
      },
      {
        tool: "modify_module",
        name: "定向修改",
        desc: "按指令定向修改某个模块，改完直接保存到简历",
        icon: Pencil,
        question: "我想定向修改一个简历模块。请先让我选择模块并说明修改目标，确认后再写入。",
      },
    ],
  },
  {
    title: "文档输出",
    subtitle: "翻译与求职文书",
    cards: [
      {
        tool: "translate",
        name: "翻译",
        desc: "把整份简历翻译为英文 / 日文等多语言版本",
        icon: Languages,
        question: "帮我把这份简历翻译成英文",
      },
      {
        tool: "cover_letter",
        name: "求职信",
        desc: "针对目标岗位一键生成求职信或打招呼语，贴合 JD 关键词",
        icon: SendHorizontal,
        question: "我想写一封求职信。请先让我提供目标岗位 JD 和称呼，信息齐全后再生成。",
      },
    ],
  },
  {
    title: "面试辅导",
    subtitle: "上场前先演练一遍",
    cards: [
      {
        tool: "interview_coach",
        name: "多轮模拟面试",
        desc: "一问一答逐题推进：生成题单 → 逐题提问与追问 → 完成自动评分出评分卡",
        icon: Mic,
        question: "我想开始模拟面试。请先确认目标岗位、面试类型和难度，再开始逐题提问。",
      },
      {
        tool: "negotiation_brief",
        name: "谈薪简报",
        desc: "生成目标岗位的薪资谈判参考：市场范围、依据与谈判要点",
        icon: HandCoins,
        question: "我想准备谈薪。请先询问目标岗位、城市、工作年限和可选的当前薪资，再生成简报。",
      },
    ],
  },
  {
    title: "知识检索",
    subtitle: "快速找到你要的内容",
    cards: [
      {
        tool: "search_resume",
        name: "简历检索",
        desc: "在简历中检索与问题相关的段落，返回带分节的结构化结果",
        icon: Search,
        question: "帮我检索这份简历里关于项目经历的内容",
      },
      {
        tool: "search_assets",
        name: "资产检索",
        desc: "跨简历、JD、面试记录等知识资产库检索相关内容",
        icon: FolderOpen,
        question: "我想检索知识资产。请先询问要找的主题，再跨简历、JD 和面试记录检索。",
      },
      {
        tool: "search_corpus",
        name: "面经知识库",
        desc: "检索离线面经 / 真题 / 范文库，快速定位可参考的面试素材",
        icon: Library,
        question: "检索面经库里的后端面试题",
      },
      {
        tool: "get_resume_content",
        name: "整文读取",
        desc: "读取简历当前完整内容（含草稿编辑态），事实性问题优先用它",
        icon: FileUser,
        question: "把这份简历的完整内容读取出来给我看看",
      },
      {
        tool: "answer_from_index",
        name: "深度问答",
        desc: "对知识库做深度检索回答（改写 → 检索 → 重排 → 生成 → 反思）",
        icon: MessageSquareText,
        question: "我想做一次有依据的深度问答。请先询问具体问题和希望使用的资料范围。",
      },
    ],
  },
  {
    title: "个人偏好",
    subtitle: "保留求职方向与关键选择",
    cards: [
      {
        tool: "save_memory",
        name: "记住",
        desc: "把你在对话中透露的重要偏好、目标、决定沉淀为长期记忆",
        icon: Bookmark,
        question: "我想保存一项求职偏好。请先询问具体内容和适用范围，确认后再记住。",
      },
      {
        tool: "recall_memory",
        name: "回忆",
        desc: "按语义召回过往对话中的记忆，保持跨会话一致",
        icon: History,
        question: "回忆一下我们之前聊过的关于我求职方向的内容",
      },
    ],
  },
];

const TOTAL_CAPABILITIES = CAPABILITY_GROUPS.reduce((sum, g) => sum + g.cards.length, 0);

/** 单张能力卡片 */
function CapabilityCardView({ card, onTrigger }: { card: CapabilityCard; onTrigger: (card: CapabilityCard) => void }) {
  return (
    <button
      type="button"
      onClick={() => onTrigger(card)}
      data-tool={card.tool}
      className="group rounded-input border border-[var(--color-border)] bg-[var(--color-surface)] p-4 text-left transition-colors hover:border-brand/40 hover:bg-[var(--color-bg-secondary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/20"
    >
      <span className="flex items-start gap-4">
        {/* 图标 */}
        <span className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-action bg-[var(--color-brand-soft)] text-brand">
          <card.icon size={20} />
        </span>

        {/* 文案 */}
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-2">
            <span className="text-sm font-semibold text-[var(--color-text)]">{card.name}</span>
          </span>
          <span className="mt-1 block text-xs leading-relaxed text-[var(--color-text-secondary)]">
            {card.desc}
          </span>
          {/* 触发问题 */}
          <span className="mt-3 flex items-center gap-1.5 text-xs font-medium text-brand">
            <span>开始任务</span>
            <ArrowRight size={13} aria-hidden="true" />
          </span>
        </span>

        {/* 引导箭头 */}
      </span>
    </button>
  );
}

/**
 * AICapabilitiesPage — AI 能力目录页。
 *
 * 点击卡片 → navigate("/qa", { state: { question } })，由 QAPage 接收
 * location.state.question 自动发起对话（与 FloatingAIPanel 快捷操作一致）。
 * 路由与导航由主协调在 App.tsx / Sidebar.tsx 中接入，本页不负责注册。
 */
export default function AICapabilitiesPage() {
  const navigate = useNavigate();
  // 携带当前上下文中已选中的简历（QAPage 上次选中后写回），
  // 让能力作用到用户真正期望的那份简历，而不是 QAPage 自动选的第一份。
  const { resumeId: ctxResumeId } = useAppChat();
  const [activeCard, setActiveCard] = useState<CapabilityCard | null>(null);
  const [formValues, setFormValues] = useState<Record<string, string>>({});
  const activeConfig = activeCard ? CAPABILITY_FORMS[activeCard.tool] : undefined;

  const navigateToTask = (card: CapabilityCard, question: string) => {
    navigate("/qa", {
      state: ctxResumeId
        ? { question, resumeId: ctxResumeId, toolHint: card.tool, newTask: true }
        : { question, toolHint: card.tool, newTask: true },
    });
  };

  const handleTrigger = (card: CapabilityCard) => {
    const config = CAPABILITY_FORMS[card.tool];
    if (config) {
      setActiveCard(card);
      setFormValues(Object.fromEntries(config.fields.map((field) => [field.key, field.defaultValue ?? ""])));
      return;
    }
    navigateToTask(card, card.question);
  };

  const closeTaskForm = () => {
    setActiveCard(null);
    setFormValues({});
  };

  const submitTaskForm = () => {
    if (!activeCard || !activeConfig) return;
    const missing = activeConfig.fields.some(
      (field) => field.required && !formValues[field.key]?.trim(),
    );
    if (missing) return;
    const question = activeConfig.buildQuestion(formValues);
    const card = activeCard;
    closeTaskForm();
    navigateToTask(card, question);
  };

  const formReady = activeConfig
    ? activeConfig.fields.every((field) => !field.required || Boolean(formValues[field.key]?.trim()))
    : false;

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-[1200px] px-4 py-6 sm:px-6 sm:py-8">
        {/* ── 头部引导 ── */}
        <div className="mb-10 animate-fade-in-up">
          <div>
            <div>
              <h1 className="text-2xl font-bold text-[var(--color-text)]">能力目录</h1>
              <p className="mt-0.5 text-sm text-[var(--color-text-secondary)]">
                {TOTAL_CAPABILITIES} 项求职任务，可直接进入对话使用
              </p>
            </div>
          </div>
        </div>

        {/* ── 能力分组卡片列表 ── */}
        {CAPABILITY_GROUPS.map((group) => (
          <section key={group.title} className="mb-10 animate-fade-in-up">
            <div className="mb-4 flex items-baseline gap-3">
              <h2 className="text-base font-semibold text-[var(--color-text)]">{group.title}</h2>
              <span className="text-xs text-[var(--color-text-muted)]">{group.subtitle}</span>
              <span className="ml-auto text-[11px] font-medium tabular-nums text-[var(--color-text-muted)]">
                {group.cards.length} 项
              </span>
            </div>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
              {group.cards.map((card) => (
                <CapabilityCardView key={card.tool} card={card} onTrigger={handleTrigger} />
              ))}
            </div>
          </section>
        ))}
      </div>

      <Modal
        open={Boolean(activeCard && activeConfig)}
        onClose={closeTaskForm}
        title={activeConfig?.title}
        size="md"
        footer={(
          <>
            <button
              type="button"
              onClick={closeTaskForm}
              className="rounded-action px-4 py-2 text-sm text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-secondary)]"
            >
              取消
            </button>
            <button
              type="button"
              onClick={submitTaskForm}
              disabled={!formReady}
              className="inline-flex items-center gap-2 rounded-action bg-brand px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:cursor-not-allowed disabled:opacity-40"
            >
              进入对话
              <ArrowRight size={14} aria-hidden="true" />
            </button>
          </>
        )}
      >
        {activeConfig && (
          <div className="space-y-4">
            <p className="text-sm leading-6 text-[var(--color-text-secondary)]">
              {activeConfig.description}
            </p>
            {activeConfig.fields.map((field) => (
              <label key={field.key} className="block space-y-1.5">
                <span className="text-sm font-medium text-[var(--color-text)]">
                  {field.label}
                  {field.required && <span className="ml-1 text-danger">*</span>}
                </span>
                {field.type === "textarea" ? (
                  <textarea
                    value={formValues[field.key] ?? ""}
                    onChange={(event) => setFormValues((current) => ({ ...current, [field.key]: event.target.value }))}
                    placeholder={field.placeholder}
                    rows={5}
                    className="w-full resize-y rounded-action border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-2.5 text-sm leading-6 text-[var(--color-text)] outline-none placeholder:text-[var(--color-text-muted)] focus:border-brand/60 focus:ring-2 focus:ring-brand/15"
                  />
                ) : field.type === "select" ? (
                  <select
                    value={formValues[field.key] ?? ""}
                    onChange={(event) => setFormValues((current) => ({ ...current, [field.key]: event.target.value }))}
                    className="w-full rounded-action border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-2.5 text-sm text-[var(--color-text)] outline-none focus:border-brand/60 focus:ring-2 focus:ring-brand/15"
                  >
                    {field.options?.map((option) => (
                      <option key={option.value} value={option.value}>{option.label}</option>
                    ))}
                  </select>
                ) : (
                  <input
                    type="text"
                    value={formValues[field.key] ?? ""}
                    onChange={(event) => setFormValues((current) => ({ ...current, [field.key]: event.target.value }))}
                    placeholder={field.placeholder}
                    className="w-full rounded-action border border-[var(--color-border)] bg-[var(--color-bg)] px-3 py-2.5 text-sm text-[var(--color-text)] outline-none placeholder:text-[var(--color-text-muted)] focus:border-brand/60 focus:ring-2 focus:ring-brand/15"
                  />
                )}
              </label>
            ))}
          </div>
        )}
      </Modal>
    </div>
  );
}
