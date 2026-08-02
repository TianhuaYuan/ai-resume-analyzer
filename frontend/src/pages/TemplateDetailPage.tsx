/**
 * TemplateDetailPage — 简历模板详情页。
 *
 * 路由：/templates/:id
 * 左侧：Mock 简历预览卡片（A4 比例）
 * 右侧：模板标题、描述、亮点标签、相关标签、适用人群
 * 底部：上/下一个模板导航 + 推荐模板网格
 */

import { useParams, useNavigate } from "react-router-dom";
import {
  CaretLeft,
  CaretRight,
  Pen,
} from "@phosphor-icons/react";
import LandingNav from "../components/LandingNav";

// ── Mock 模板详情数据 ──

interface TemplateDetail {
  id: number;
  title: string;
  date: string;
  description: string;
  highlights: string[];
  tags: string[];
  relatedTags: string[];
  targetAudience: string;
  gradient: string;
  accentColor: string;
}

const TEMPLATE_DETAILS: Record<number, TemplateDetail> = {
  1: {
    id: 1,
    title: "仿真算法工程师简历模板（高端制造/航空航天校招）",
    date: "2026-08-02",
    description:
      "专为高端制造与航空航天领域设计的仿真算法工程师简历模板。突出 MATLAB/Simulink 仿真建模能力、CFD/FEA 分析经验及项目成果量化数据。采用简洁专业的布局，帮助应届生快速展示技术实力与工程实践经历。",
    highlights: [
      "突出仿真建模与算法能力",
      "适配高端制造与航空航天行业",
      "强调量化成果与项目经历",
      "校招专用结构优化",
    ],
    tags: ["机械类", "仿真工程师", "校招简历", "航空航天"],
    relatedTags: [
      "#仿真算法",
      "#MATLAB",
      "#CFD",
      "#FEA",
      "#高端制造",
      "#航空航天",
    ],
    targetAudience:
      "本模板特别适合仿真算法工程师（校招）岗位的求职者使用。具备相关项目经历的工科应届生，通过专业技术风格的设计，帮助您在高端制造与航空航天行业中脱颖而出，展现专业形象和核心竞争力。",
    gradient: "from-blue-500/20 to-indigo-500/10",
    accentColor: "bg-blue-500/30",
  },
  2: {
    id: 2,
    title: "技术支持工程师（FAE）简历模板 - 半导体/企业服务校招专用",
    date: "2026-08-02",
    description:
      "专为半导体及企业服务行业校招设计的技术支持工程师（FAE）简历模板。突出 Unix/Linux 系统操作、Python 脚本能力、客户沟通技巧、问题定位分析及技术培训经验。采用清晰专业的布局，帮助应届生快速展示技术实力与服务意识，精准匹配 FAE 岗位需求。",
    highlights: [
      "突出技术栈与客户沟通能力",
      "适配半导体与企业服务行业场景",
      "强调问题定位与技术培训经历",
      "校招专用结构优化",
    ],
    tags: ["电子信息类", "程序员简历", "校招简历", "科技行业"],
    relatedTags: [
      "#技术支持工程师",
      "#FAE简历",
      "#半导体校招",
      "#Unix/Linux",
      "#Python",
      "#客户沟通",
      "#问题定位",
      "#技术培训",
    ],
    targetAudience:
      "本模板特别适合技术支持工程师（FAE）岗位的求职者使用。具备应届生工作经验的专业人士，通过技术类风格的设计，帮助您在半导体/企业服务行业中脱颖而出，展现专业形象和核心竞争力。",
    gradient: "from-emerald-500/20 to-teal-500/10",
    accentColor: "bg-emerald-500/30",
  },
  3: {
    id: 3,
    title: "算法工程师（大模型/AI方向）简历模板 - 互联网校招专用",
    date: "2026-08-01",
    description:
      "专为互联网大模型与 AI 方向校招设计的算法工程师简历模板。突出 PyTorch/TensorFlow 框架经验、大模型微调与训练能力、论文发表及竞赛成绩。采用前沿技术风格的布局，帮助应届生精准展示 AI 领域的专业素养。",
    highlights: [
      "突出大模型与深度学习能力",
      "适配互联网 AI 方向校招场景",
      "强调论文发表与竞赛成绩",
      "技术栈可视化展示",
    ],
    tags: ["AI人工智能", "应届生简历", "校招简历", "互联网"],
    relatedTags: [
      "#大模型",
      "#PyTorch",
      "#深度学习",
      "#NLP",
      "#算法工程师",
      "#机器学习",
    ],
    targetAudience:
      "本模板特别适合算法工程师（大模型/AI方向）岗位的应届求职者。通过技术风格的设计，帮助您在互联网校招中展现 AI 领域的专业积累和研究能力。",
    gradient: "from-violet-500/20 to-purple-500/10",
    accentColor: "bg-violet-500/30",
  },
  4: {
    id: 4,
    title: "产品经理（应用/供应链方向）校招简历模板-互联网智能制造",
    date: "2026-07-30",
    description:
      "专为互联网与智能制造领域校招设计的产品经理简历模板。突出产品规划、用户调研、数据分析和跨部门协作能力。采用专业简洁的布局，帮助应届生快速展示产品思维与业务理解。",
    highlights: [
      "突出产品规划与用户洞察能力",
      "适配互联网与智能制造行业",
      "强调数据分析与业务理解",
      "校招专用结构优化",
    ],
    tags: ["互联网", "产品经理", "校招简历", "智能制造"],
    relatedTags: [
      "#产品经理",
      "#用户调研",
      "#数据分析",
      "#Axure",
      "#PRD",
      "#互联网校招",
    ],
    targetAudience:
      "本模板特别适合产品经理岗位的校招求职者。通过专业风格的设计，帮助您在互联网与智能制造行业中展现产品思维和业务理解能力。",
    gradient: "from-amber-500/20 to-orange-500/10",
    accentColor: "bg-amber-500/30",
  },
  5: {
    id: 5,
    title: "前端开发工程师简历模板 - React/Vue方向",
    date: "2026-07-28",
    description:
      "专为前端开发方向校招设计的简历模板。突出 React/Vue 框架经验、TypeScript 能力、组件化开发和性能优化经验。采用现代技术风格的布局，帮助应届生快速展示前端工程能力。",
    highlights: [
      "突出 React/Vue 框架能力",
      "适配前端开发校招场景",
      "强调组件化与性能优化",
      "技术栈可视化展示",
    ],
    tags: ["程序员简历", "应届生简历", "校招简历", "前端开发"],
    relatedTags: [
      "#React",
      "#Vue",
      "#TypeScript",
      "#前端开发",
      "#性能优化",
      "#组件化",
    ],
    targetAudience:
      "本模板特别适合前端开发工程师岗位的校招求职者。通过现代技术风格的设计，帮助您在互联网校招中展现前端工程能力和技术积累。",
    gradient: "from-cyan-500/20 to-sky-500/10",
    accentColor: "bg-cyan-500/30",
  },
  6: {
    id: 6,
    title: "数据分析师简历模板 - 互联网/金融方向",
    date: "2026-07-25",
    description:
      "专为数据分析师校招设计的简历模板。突出 SQL、Python 数据处理、BI 工具使用及业务洞察能力。采用数据驱动风格的布局，帮助应届生快速展示数据分析与商业思维。",
    highlights: [
      "突出 SQL/Python 数据处理能力",
      "适配互联网与金融行业",
      "强调业务洞察与 BI 可视化",
      "校招专用结构优化",
    ],
    tags: ["数据分析师", "应届生简历", "校招简历", "互联网金融"],
    relatedTags: [
      "#数据分析",
      "#SQL",
      "#Python",
      "#Tableau",
      "#业务洞察",
      "#金融校招",
    ],
    targetAudience:
      "本模板特别适合数据分析师岗位的校招求职者。通过数据驱动风格的设计，帮助您在互联网与金融行业中展现数据分析能力和商业思维。",
    gradient: "from-rose-500/20 to-pink-500/10",
    accentColor: "bg-rose-500/30",
  },
  7: {
    id: 7,
    title: "UI/UX设计师简历模板 - 互联网/设计方向",
    date: "2026-07-22",
    description:
      "专为 UI/UX 设计师校招设计的简历模板。突出设计工具熟练度、用户体验研究能力和设计系统思维。采用视觉优先风格的布局，帮助应届生快速展示设计审美与专业能力。",
    highlights: [
      "突出设计工具与用户体验能力",
      "适配互联网与设计行业",
      "强调设计系统与作品集展示",
      "视觉优先的布局设计",
    ],
    tags: ["设计师简历", "应届生简历", "校招简历", "互联网设计"],
    relatedTags: [
      "#UI设计",
      "#UX设计",
      "#Figma",
      "#Sketch",
      "#设计系统",
      "#用户体验",
    ],
    targetAudience:
      "本模板特别适合 UI/UX 设计师岗位的校招求职者。通过视觉优先风格的设计，帮助您在互联网与设计行业中展现设计审美和专业能力。",
    gradient: "from-fuchsia-500/20 to-pink-500/10",
    accentColor: "bg-fuchsia-500/30",
  },
  8: {
    id: 8,
    title: "嵌入式软件工程师简历模板 - 智能硬件/机器人校招",
    date: "2026-07-20",
    description:
      "专为嵌入式软件工程师校招设计的简历模板。突出 C/C++ 编程能力、RTOS 经验、硬件调试能力和嵌入式系统设计经验。采用硬件技术风格的布局，帮助应届生快速展示嵌入式开发实力。",
    highlights: [
      "突出 C/C++ 与嵌入式系统能力",
      "适配智能硬件与机器人行业",
      "强调硬件调试与 RTOS 经验",
      "校招专用结构优化",
    ],
    tags: ["电子信息类", "应届生简历", "校招简历", "智能硬件"],
    relatedTags: [
      "#嵌入式",
      "#C语言",
      "#RTOS",
      "#STM32",
      "#机器人",
      "#智能硬件",
    ],
    targetAudience:
      "本模板特别适合嵌入式软件工程师岗位的校招求职者。通过硬件技术风格的设计，帮助您在智能硬件与机器人行业中展现嵌入式开发实力和工程实践能力。",
    gradient: "from-teal-500/20 to-emerald-500/10",
    accentColor: "bg-teal-500/30",
  },
};

const ALL_IDS = [1, 2, 3, 4, 5, 6, 7, 8];

// ── Mock 简历预览内容 ──

function ResumePreviewCard({ template }: { template: TemplateDetail }) {
  return (
    <div className="w-full max-w-[400px] mx-auto">
      <div className="bg-white rounded-2xl shadow-lg border border-gray-200 overflow-hidden">
        {/* 简历头部 */}
        <div className="bg-gray-50 px-5 py-4 text-center border-b border-gray-100">
          <div className="w-14 h-14 rounded-full bg-gray-200 mx-auto mb-2" />
          <div className="text-base font-bold text-gray-900">张三</div>
          <div className="text-[10px] text-gray-500 mt-0.5">
            {template.title.split("简历模板")[0]}
          </div>
          <div className="flex items-center justify-center gap-3 mt-1.5 text-[9px] text-gray-400">
            <span>上海</span>
            <span>139-0000-0000</span>
            <span>zhangsan@example.com</span>
          </div>
        </div>

        {/* 简历内容 */}
        <div className="p-5 space-y-4 text-[10px] leading-relaxed text-gray-700">
          {/* 教育背景 */}
          <div>
            <div className="text-[11px] font-bold text-brand border-b border-brand/20 pb-1 mb-2">
              教育背景
            </div>
            <div className="flex justify-between items-start">
              <div>
                <div className="font-semibold text-gray-900">XX大学</div>
                <div className="text-gray-500">电子信息工程 · 本科</div>
              </div>
              <div className="text-gray-400 shrink-0">2022-09 ~ 2026-06</div>
            </div>
          </div>

          {/* 项目经历 */}
          <div>
            <div className="text-[11px] font-bold text-brand border-b border-brand/20 pb-1 mb-2">
              项目经历
            </div>
            <div className="font-semibold text-gray-900">
              {template.title.split("简历模板")[0]}项目
            </div>
            <div className="text-gray-500 text-[9px]">2025-01 ~ 2025-05</div>
            <ul className="list-disc list-inside mt-1 space-y-0.5 text-gray-600">
              <li>负责核心模块的设计与开发，优化系统性能</li>
              <li>参与技术方案评审，输出技术文档</li>
              <li>完成代码审查与单元测试，保障代码质量</li>
            </ul>
          </div>

          {/* 专业技能 */}
          <div>
            <div className="text-[11px] font-bold text-brand border-b border-brand/20 pb-1 mb-2">
              专业技能
            </div>
            <div className="flex flex-wrap gap-1.5">
              {template.relatedTags.slice(0, 6).map((tag) => (
                <span
                  key={tag}
                  className="px-2 py-0.5 rounded bg-brand/10 text-brand text-[9px]"
                >
                  {tag.replace("#", "")}
                </span>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── 主组件 ──

export default function TemplateDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const templateId = Number(id);
  const template = TEMPLATE_DETAILS[templateId];

  if (!template) {
    return (
      <div className="min-h-screen bg-[var(--color-bg)]">
        <LandingNav activeKey="templates" />
        <div className="max-w-7xl mx-auto px-6 py-20 text-center">
          <p className="text-[var(--color-text-muted)] text-sm">模板不存在</p>
          <button
            onClick={() => navigate("/templates")}
            className="mt-4 text-brand text-sm hover:underline cursor-pointer"
          >
            返回模板列表
          </button>
        </div>
      </div>
    );
  }

  const currentIndex = ALL_IDS.indexOf(templateId);
  const prevId = currentIndex > 0 ? ALL_IDS[currentIndex - 1] : null;
  const nextId =
    currentIndex < ALL_IDS.length - 1 ? ALL_IDS[currentIndex + 1] : null;
  const prevT = prevId ? TEMPLATE_DETAILS[prevId] : null;
  const nextT = nextId ? TEMPLATE_DETAILS[nextId] : null;

  // 推荐模板（排除当前）
  const recommended = ALL_IDS
    .filter((i) => i !== templateId)
    .slice(0, 4)
    .map((i) => TEMPLATE_DETAILS[i]);

  return (
    <div className="min-h-screen bg-[var(--color-bg)]">
      <LandingNav activeKey="templates" />

      <div className="max-w-7xl mx-auto px-6 py-6">
        {/* 面包屑 */}
        <nav className="flex items-center gap-1.5 text-xs text-[var(--color-text-muted)] mb-6">
          <button
            onClick={() => navigate("/")}
            className="hover:text-brand transition-colors cursor-pointer"
          >
            首页
          </button>
          <CaretRight size={10} />
          <button
            onClick={() => navigate("/templates")}
            className="hover:text-brand transition-colors cursor-pointer"
          >
            简历模板
          </button>
          <CaretRight size={10} />
          <span className="text-[var(--color-text)] font-medium truncate max-w-[300px]">
            {template.title}
          </span>
        </nav>

        {/* 主体：预览 + 信息 */}
        <div className="flex flex-col lg:flex-row gap-10 mb-16">
          {/* 左侧：预览 */}
          <div className="flex-1 flex justify-center">
            <ResumePreviewCard template={template} />
          </div>

          {/* 右侧：模板信息 */}
          <div className="flex-1 max-w-lg">
            <div className="flex items-start justify-between gap-4 mb-4">
              <h1 className="text-2xl font-bold text-[var(--color-text)] leading-tight display-tight">
                {template.title}
              </h1>
              <span className="text-xs text-[var(--color-text-muted)] shrink-0 tabular-nums">
                {template.date}
              </span>
            </div>

            <p className="text-sm text-[var(--color-text-secondary)] leading-relaxed mb-6">
              {template.description}
            </p>

            {/* 模板亮点 */}
            <h2 className="text-base font-semibold text-[var(--color-text)] mb-3">
              模板亮点
            </h2>
            <div className="flex flex-wrap gap-2 mb-6">
              {template.highlights.map((h) => (
                <span
                  key={h}
                  className="px-3 py-1.5 rounded-full text-xs font-medium bg-brand/10 text-brand border border-brand/20"
                >
                  {h}
                </span>
              ))}
            </div>

            {/* 相关标签 */}
            <h2 className="text-base font-semibold text-[var(--color-text)] mb-3">
              相关标签
            </h2>
            <div className="flex flex-wrap gap-2 mb-6">
              {template.tags.map((t) => (
                <span
                  key={t}
                  className="px-3 py-1.5 rounded-full text-xs font-medium bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)] border border-[var(--color-border)]"
                >
                  {t}
                </span>
              ))}
            </div>
            <div className="flex flex-wrap gap-2 mb-6">
              {template.relatedTags.map((t) => (
                <span
                  key={t}
                  className="px-3 py-1.5 rounded-full text-xs font-medium bg-brand/5 text-brand/70 border border-brand/10"
                >
                  {t}
                </span>
              ))}
            </div>

            {/* 适用人群 */}
            <h2 className="text-base font-semibold text-[var(--color-text)] mb-3">
              适用人群
            </h2>
            <p className="text-sm text-[var(--color-text-secondary)] leading-relaxed mb-6 p-4 rounded-xl bg-[var(--color-bg-secondary)] border border-[var(--color-border)]">
              {template.targetAudience}
            </p>

            {/* CTA 按钮 */}
            <button
              onClick={() => navigate(`/resumes/new?template=${templateId}`)}
              className="w-full flex items-center justify-center gap-2 py-3.5 rounded-xl bg-brand text-white font-semibold text-sm
                hover:bg-[#0077ed] hover:scale-[1.02] active:scale-[0.98]
                transition-all duration-300 cursor-pointer"
            >
              <Pen size={16} weight="regular" />
              使用模板创建简历
            </button>
          </div>
        </div>

        {/* 上/下一个模板 */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-5 mb-16">
          {prevT ? (
            <button
              onClick={() => navigate(`/templates/${prevId}`)}
              className="glass-card p-5 text-left hover:-translate-y-1 hover:shadow-xl transition-all duration-400 cursor-pointer group"
            >
              <div className="flex items-center gap-1.5 text-xs text-[var(--color-text-muted)] mb-2">
                <CaretLeft
                  size={12}
                  className="group-hover:-translate-x-1 transition-transform"
                />
                上一个模板
              </div>
              <h3 className="text-sm font-semibold text-[var(--color-text)] leading-snug">
                {prevT.title}
              </h3>
              <span className="text-[10px] text-[var(--color-text-muted)]">
                技术类
              </span>
            </button>
          ) : (
            <div />
          )}
          {nextT ? (
            <button
              onClick={() => navigate(`/templates/${nextId}`)}
              className="glass-card p-5 text-right hover:-translate-y-1 hover:shadow-xl transition-all duration-400 cursor-pointer group"
            >
              <div className="flex items-center justify-end gap-1.5 text-xs text-[var(--color-text-muted)] mb-2">
                下一个模板
                <CaretRight
                  size={12}
                  className="group-hover:translate-x-1 transition-transform"
                />
              </div>
              <h3 className="text-sm font-semibold text-[var(--color-text)] leading-snug">
                {nextT.title}
              </h3>
              <span className="text-[10px] text-[var(--color-text-muted)]">
                技术类
              </span>
            </button>
          ) : (
            <div />
          )}
        </div>

        {/* 推荐模板 */}
        <div className="mb-16">
          <h2 className="text-lg font-bold text-[var(--color-text)] text-center mb-6">
            同样优秀的技术类风格模板
          </h2>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-5">
            {recommended.map((t) => (
              <div
                key={t.id}
                className="glass-card overflow-hidden hover:-translate-y-1 hover:shadow-xl transition-all duration-400 cursor-pointer group"
                onClick={() => navigate(`/templates/${t.id}`)}
              >
                <div
                  className={`aspect-[3/4] bg-gradient-to-br ${t.gradient} p-4 flex flex-col justify-between`}
                >
                  <div className="bg-white rounded-lg shadow-sm p-3 flex-1 overflow-hidden">
                    <div className="flex items-center gap-2 mb-2">
                      <div className="w-6 h-6 rounded-full bg-gray-200" />
                      <div>
                        <div className="w-12 h-1.5 bg-gray-300 rounded" />
                        <div className="w-8 h-1 bg-gray-200 rounded mt-0.5" />
                      </div>
                    </div>
                    {[...Array(6)].map((_, i) => (
                      <div key={i} className="flex gap-1 mb-1">
                        <div
                          className={`h-1 rounded ${i % 3 === 0 ? "w-full" : i % 3 === 1 ? "w-3/4" : "w-1/2"} bg-gray-200`}
                        />
                      </div>
                    ))}
                    <div className="mt-2 flex gap-1">
                      <div
                        className={`h-1 rounded ${t.accentColor} w-8`}
                      />
                      <div className="h-1 rounded bg-gray-200 w-16" />
                    </div>
                    {[...Array(4)].map((_, i) => (
                      <div
                        key={i}
                        className="flex gap-1 mb-0.5 mt-0.5"
                      >
                        <div className="h-1 rounded bg-gray-200 w-3/4" />
                      </div>
                    ))}
                  </div>
                </div>
                <div className="p-3">
                  <h3 className="text-xs font-semibold text-[var(--color-text)] leading-snug line-clamp-2">
                    {t.title}
                  </h3>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
