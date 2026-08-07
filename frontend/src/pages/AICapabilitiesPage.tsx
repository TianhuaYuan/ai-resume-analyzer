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

import { useNavigate } from "react-router-dom";
import { useAppChat } from "../context/AppChatContext";
import {
  FirstAidKit,
  Scales,
  CheckCircle,
  Crosshair,
  Briefcase,
  FileText,
  FilePlus,
  Star,
  Translate,
  PencilSimple,
  Question,
  Microphone,
  MagnifyingGlass,
  FolderOpen,
  GlobeSimple,
  HandCoins,
  Books,
  ReadCvLogo,
  ChatCircleText,
  BookmarkSimple,
  ClockCounterClockwise,
  Sparkle,
  ArrowRight,
  PaperPlaneRight,
} from "@phosphor-icons/react";

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
        icon: FirstAidKit,
        question: "帮我诊断这份简历的完整性和质量，给出改进建议",
      },
      {
        tool: "compare_resumes",
        name: "简历对比",
        desc: "横向对比多份简历的优劣势，给出综合裁决",
        icon: Scales,
        question: "帮我对比我选中的几份简历，分析各自的优劣势",
      },
      {
        tool: "check_module",
        name: "模块检查",
        desc: "检查简历各模块的完整性和 ATS 兼容性，不修改内容",
        icon: CheckCircle,
        question: "帮我检查简历各模块的完整性和 ATS 兼容性",
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
        question: "帮我分析这份简历和目标岗位 JD 的匹配度，指出差距在哪里",
      },
      {
        tool: "search_jobs_live",
        name: "岗位推荐",
        desc: "实时搜索匹配的校招 / 社招 / 实习岗位",
        icon: Briefcase,
        question: "请实时搜索最近的校招和社招岗位机会",
      },
      {
        tool: "web_search",
        name: "联网搜索",
        desc: "实时搜索面经 / 薪资 / 公司评价等信息，弥补离线知识库的时效性缺口",
        icon: GlobeSimple,
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
        name: "整份生成 / 优化",
        desc: "空简历一键生成完整简历，或按目标岗位优化现有内容",
        icon: FileText,
        question: "帮我重新生成并优化这份简历，让它更专业更有竞争力",
      },
      {
        tool: "generate_module",
        name: "模块生成",
        desc: "AI 生成指定模块内容（如教育背景、工作经历），直接写入简历",
        icon: FilePlus,
        question: "帮我生成简历中缺失的模块内容，比如教育背景或工作经历",
      },
      {
        tool: "rewrite_star",
        name: "STAR 改写",
        desc: "用 STAR 法则改写经历描述，让表达更专业、更有说服力",
        icon: Star,
        question: "用 STAR 法则改写我简历里的经历描述，让它们更有说服力",
      },
      {
        tool: "translate",
        name: "翻译",
        desc: "把整份简历翻译为英文 / 日文等多语言版本",
        icon: Translate,
        question: "帮我把这份简历翻译成英文",
      },
      {
        tool: "cover_letter",
        name: "求职信",
        desc: "针对目标岗位一键生成求职信或打招呼语，贴合 JD 关键词",
        icon: PaperPlaneRight,
        question: "帮我在这个简历的基础上，针对目标岗位写一封求职信",
      },
      {
        tool: "modify_module",
        name: "定向修改",
        desc: "按指令定向修改某个模块，改完直接保存到简历",
        icon: PencilSimple,
        question: "帮我定向修改简历中的某个模块，比如把项目描述改得更量化",
      },
      {
        tool: "ask_info",
        name: "信息追问",
        desc: "分析简历缺失项，提醒你还差哪些信息需要补充",
        icon: Question,
        question: "根据简历现状，帮我梳理还需要补充哪些信息",
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
        icon: Microphone,
        question: "请根据我的简历，帮我做一次目标岗位的模拟面试",
      },
      {
        tool: "negotiation_brief",
        name: "谈薪简报",
        desc: "生成目标岗位的薪资谈判参考：市场范围、依据与谈判要点",
        icon: HandCoins,
        question: "帮我生成后端岗位的谈薪简报",
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
        icon: MagnifyingGlass,
        question: "帮我检索这份简历里关于项目经历的内容",
      },
      {
        tool: "search_assets",
        name: "资产检索",
        desc: "跨简历、JD、面试记录等知识资产库检索相关内容",
        icon: FolderOpen,
        question: "帮我在我的知识资产库（简历 / JD / 面试记录）里检索相关内容",
      },
      {
        tool: "search_corpus",
        name: "面经知识库",
        desc: "检索离线面经 / 真题 / 范文库，快速定位可参考的面试素材",
        icon: Books,
        question: "检索面经库里的后端面试题",
      },
      {
        tool: "get_resume_content",
        name: "整文读取",
        desc: "读取简历当前完整内容（含草稿编辑态），事实性问题优先用它",
        icon: ReadCvLogo,
        question: "把这份简历的完整内容读取出来给我看看",
      },
      {
        tool: "answer_from_index",
        name: "深度问答",
        desc: "对知识库做深度检索回答（改写 → 检索 → 重排 → 生成 → 反思）",
        icon: ChatCircleText,
        question: "基于我的简历和知识库，深度回答一个问题并给出依据",
      },
    ],
  },
  {
    title: "记忆",
    subtitle: "AI 记得住你的偏好",
    cards: [
      {
        tool: "save_memory",
        name: "记住",
        desc: "把你在对话中透露的重要偏好、目标、决定沉淀为长期记忆",
        icon: BookmarkSimple,
        question: "请记住我的求职偏好：优先考虑一线大厂的后端岗位",
      },
      {
        tool: "recall_memory",
        name: "回忆",
        desc: "按语义召回过往对话中的记忆，保持跨会话一致",
        icon: ClockCounterClockwise,
        question: "回忆一下我们之前聊过的关于我求职方向的内容",
      },
    ],
  },
];

const TOTAL_CAPABILITIES = CAPABILITY_GROUPS.reduce((sum, g) => sum + g.cards.length, 0);

/** 单张能力卡片 */
function CapabilityCardView({ card, onTrigger }: { card: CapabilityCard; onTrigger: (question: string) => void }) {
  return (
    <button
      type="button"
      onClick={() => onTrigger(card.question)}
      data-tool={card.tool}
      className="group glass-card p-5 text-left transition-all duration-300 hover:-translate-y-1 hover:shadow-xl hover:shadow-black/5 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-brand/15"
    >
      <span className="flex items-start gap-4">
        {/* 图标 */}
        <span className="flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-2xl bg-[var(--color-brand-soft)] text-brand">
          <card.icon size={22} weight="duotone" />
        </span>

        {/* 文案 */}
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-2">
            <span className="text-sm font-semibold text-[var(--color-text)]">{card.name}</span>
            <span className="font-mono-label rounded bg-[var(--color-bg-secondary)] px-1.5 py-0.5 text-[10px] text-[var(--color-text-muted)]">
              {card.tool}
            </span>
          </span>
          <span className="mt-1 block text-xs leading-relaxed text-[var(--color-text-secondary)]">
            {card.desc}
          </span>
          {/* 触发问题 */}
          <span className="mt-3 flex items-start gap-1.5 text-xs text-brand/90">
            <Sparkle size={13} weight="fill" className="mt-0.5 flex-shrink-0" />
            <span className="line-clamp-2 leading-relaxed">{card.question}</span>
          </span>
        </span>

        {/* 引导箭头 */}
        <ArrowRight
          size={16}
          className="mt-1 flex-shrink-0 text-[var(--color-text-muted)] transition-transform duration-200 group-hover:translate-x-0.5 group-hover:text-brand"
        />
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

  const handleTrigger = (question: string) => {
    navigate("/qa", {
      state: ctxResumeId ? { question, resumeId: ctxResumeId } : { question },
    });
  };

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-[1200px] px-6 py-8">
        {/* ── 头部引导 ── */}
        <div className="mb-10 animate-fade-in-up">
          <div className="flex items-center gap-3">
            <span className="flex h-12 w-12 flex-shrink-0 items-center justify-center rounded-2xl bg-brand text-white shadow-lg shadow-brand/25">
              <Sparkle size={24} weight="fill" />
            </span>
            <div>
              <h1 className="text-2xl font-bold text-[var(--color-text)]">AI 能力目录</h1>
              <p className="mt-0.5 text-sm text-[var(--color-text-secondary)]">
                {TOTAL_CAPABILITIES} 项 AI 能力，点一下直接干活
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
    </div>
  );
}
