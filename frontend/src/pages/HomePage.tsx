/**
 * HomePage — 网站首页（纯展示介绍页）
 *
 * P0 重设计（2026-08-09）：
 * - 复用 ui/ 基础组件（Button / Badge），验证组件库分层落地
 * - Hero 品牌渐变大标题 + 信任数据 + 双 CTA
 * - 升级版产品展示（ATS 诊断卡 + 打字指示器 + 关键词高亮）
 * - 6 格 Bento 功能 + 三步工作流 + 底部渐变 CTA
 * 内容页（模板/范文/攻略等）由各自独立页面直接展示，首页不做内容承载。
 */

import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import LandingNav from "../components/LandingNav";
import { Button, Badge } from "../components/ui";
import { ArrowRight, MessagesSquare, FileText, Target, BadgeCheck, Briefcase, Mic, Upload, Compass } from "lucide-react";

// ── Hero 信任数据 ──

const HERO_STATS = [
  { value: "22 项", label: "求职任务" },
  { value: "18 套", label: "简历模板" },
  { value: "全链路", label: "修改可确认" },
];

// ── Bento 功能卡 ──

interface Feature {
  icon: typeof MessagesSquare;
  title: string;
  desc: string;
  /** icon 底色 + 文字色（浅色 alpha，双主题可读） */
  tint: string;
}

const FEATURES: Feature[] = [
  { icon: MessagesSquare, title: "对话式任务台", desc: "诊断、改写、岗位匹配和检索都从明确任务进入，过程与结果可回看", tint: "bg-brand/10 text-brand" },
  { icon: FileText, title: "专业简历编辑器", desc: "Tiptap 所见即所得，模块自由增删排序，一键预览与导出", tint: "bg-sky-500/10 text-sky-500" },
  { icon: BadgeCheck, title: "证据化诊断", desc: "区分原文已证明、证据不足和明确缺失，不把参考分包装成通过率", tint: "bg-success-soft text-success" },
  { icon: Briefcase, title: "投递工作台", desc: "保存岗位、跟踪进度与关键时间点，JD 可沉淀为后续检索资料", tint: "bg-warning-soft text-warning" },
  { icon: Mic, title: "面试训练与复盘", desc: "围绕目标岗位练习，记录问题、回答、评分维度和下一步行动", tint: "bg-purple-500/10 text-purple-500" },
  { icon: Target, title: "个人求职知识库", desc: "把简历、JD、面试记录和笔记放在同一套可检索的资料中", tint: "bg-rose-500/10 text-rose-500" },
];

// ── 三步工作流 ──

const STEPS = [
  { icon: Upload, step: "01", title: "上传简历", desc: "PDF / DOCX 一键上传，自动解析为结构化内容" },
  { icon: Target, step: "02", title: "核对并修改", desc: "检查解析结果和岗位证据，逐条确认修改，不自动覆盖" },
  { icon: Briefcase, step: "03", title: "投递与复盘", desc: "跟踪申请进度，沉淀面试问题、评分和训练计划" },
];

// ── 产品展示模型（浏览器窗口 + Agent 聊天 + 简历预览） ──

function ProductMockup() {
  return (
    <div className="relative max-w-5xl mx-auto mt-12 px-4">
      {/* 外层容器：模拟浏览器窗口 */}
      <div className="rounded-[24px] overflow-hidden border border-[var(--color-border)] bg-[var(--color-surface)] shadow-xl shadow-black/8">
        {/* 浏览器顶栏 */}
        <div className="flex items-center gap-2 px-4 py-2.5 bg-[var(--color-bg-secondary)] border-b border-[var(--color-border)]">
          <div className="flex gap-1.5">
            <div className="w-2.5 h-2.5 rounded-full bg-danger/70" />
            <div className="w-2.5 h-2.5 rounded-full bg-warning/70" />
            <div className="w-2.5 h-2.5 rounded-full bg-success/70" />
          </div>
          <div className="flex-1 flex justify-center">
            <div className="flex items-center gap-3 text-[10px] text-[var(--color-text-muted)]">
              <span className="px-3 py-0.5 rounded-full bg-brand/10 text-brand font-medium">Agent</span>
              <span className="px-3 py-0.5 rounded-full hover:bg-[var(--color-bg-secondary)] cursor-pointer">简历构建</span>
              <span className="px-3 py-0.5 rounded-full hover:bg-[var(--color-bg-secondary)] cursor-pointer">ATS 诊断</span>
            </div>
          </div>
        </div>

        {/* 内容区：左 Agent + 右 简历预览 */}
        <div className="flex min-h-[360px] md:min-h-[440px]">
          {/* 左侧：Agent 聊天 */}
          <div className="flex-1 border-r border-[var(--color-border)] p-4 flex flex-col gap-3">
            {/* 系统消息 */}
            <div className="flex gap-2">
              <div className="w-6 h-6 rounded-full bg-brand/10 flex items-center justify-center shrink-0">
                <Compass size={12} fill="currentColor" className="text-brand" />
              </div>
              <div className="bg-[var(--color-bg-secondary)] rounded-list rounded-tl-sm px-3 py-2 text-xs text-[var(--color-text-secondary)] leading-relaxed max-w-[85%]">
                已读取当前简历。你可以先做岗位匹配，也可以从某个具体条目开始检查。
              </div>
            </div>
            {/* 用户消息 */}
            <div className="flex gap-2 justify-end">
              <div className="bg-brand text-white rounded-list rounded-tr-sm px-3 py-2 text-xs leading-relaxed max-w-[85%]">
                检查项目经历和目标岗位的证据是否对应。
              </div>
            </div>
            {/* ATS 诊断卡（模拟实时分析结果） */}
            <div className="flex gap-2">
              <div className="w-6 h-6 rounded-full bg-brand/10 flex items-center justify-center shrink-0">
                <Compass size={12} fill="currentColor" className="text-brand" />
              </div>
              <div className="flex-1 max-w-[85%] bg-white/70 dark:bg-white/5 border border-[var(--color-border)] rounded-list p-3">
                <div className="flex items-center justify-between text-[10px] mb-1.5">
                  <span className="text-[var(--color-text-muted)] font-medium">文本证据检查</span>
                  <span className="text-brand font-semibold tabular-nums">3 / 5</span>
                </div>
                <div className="h-1.5 rounded-full bg-[var(--color-bg-secondary)] overflow-hidden">
                  <div className="h-full w-[60%] rounded-full bg-brand" />
                </div>
                <div className="flex flex-wrap gap-1 mt-2">
                  {["3 条直接证据", "2 条待补充", "来源可回看"].map((t) => (
                    <span key={t} className="px-1.5 py-0.5 rounded-full bg-success-soft text-success text-[9px] font-medium">
                      ✓ {t}
                    </span>
                  ))}
                </div>
              </div>
            </div>
            {/* 系统回复 */}
            <div className="flex gap-2">
              <div className="w-6 h-6 rounded-full bg-brand/10 flex items-center justify-center shrink-0">
                <Compass size={12} fill="currentColor" className="text-brand" />
              </div>
              <div className="bg-[var(--color-bg-secondary)] rounded-list rounded-tl-sm px-3 py-2 text-xs text-[var(--color-text-secondary)] leading-relaxed max-w-[85%]">
                当前有 3 条要求能在简历中直接定位；另外 2 条只有技能关键词，项目深度仍需补充。
              </div>
            </div>
            {/* 打字指示器（Open WebUI 风格两粒圆点） */}
            <div className="flex gap-2">
              <div className="w-6 h-6 rounded-full bg-brand/10 flex items-center justify-center shrink-0">
                <Compass size={12} fill="currentColor" className="text-brand" />
              </div>
              <div className="bg-[var(--color-bg-secondary)] rounded-list rounded-tl-sm px-3 py-2.5">
                <div className="flex gap-1">
                  <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-text-muted)] animate-pulse" />
                  <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-text-muted)] animate-pulse" style={{ animationDelay: "150ms" }} />
                  <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-text-muted)] animate-pulse" style={{ animationDelay: "300ms" }} />
                </div>
              </div>
            </div>
          </div>

          {/* 右侧：简历预览（含 ATS 关键词高亮） */}
          <div className="hidden md:block flex-1 p-4 bg-[var(--color-bg)]">
            <div className="bg-white rounded-action shadow-sm border border-gray-200 p-5 h-full text-gray-800 text-[10px] leading-relaxed">
              {/* 简历头部 */}
              <div className="text-center mb-3">
                <div className="text-sm font-bold text-gray-900">轻舟简历</div>
                <div className="text-[10px] text-gray-500 mt-0.5">软件开发实习生</div>
                <div className="flex items-center justify-center gap-3 mt-1.5 text-[9px] text-gray-400">
                  <span>北京</span>
                  <span>139-0000-0000</span>
                  <span>airecv@example.com</span>
                </div>
              </div>
              {/* 技能：关键词高亮 */}
              <div className="mb-2">
                <div className="text-[10px] font-bold text-blue-600 border-b border-blue-200 pb-0.5 mb-1">技能</div>
                <div className="flex flex-wrap gap-1">
                  <span className="px-1.5 py-0.5 rounded bg-brand/10 text-brand font-medium">React</span>
                  <span className="px-1.5 py-0.5 rounded bg-brand/10 text-brand font-medium">TypeScript</span>
                  <span className="px-1.5 py-0.5 rounded bg-gray-100 text-gray-500">HTML/CSS</span>
                  <span className="px-1.5 py-0.5 rounded bg-gray-100 text-gray-500">Git</span>
                </div>
              </div>
              {/* 教育经历 */}
              <div className="mb-2">
                <div className="text-[10px] font-bold text-blue-600 border-b border-blue-200 pb-0.5 mb-1">教育经历</div>
                <div className="text-[9px]">
                  <div className="flex justify-between">
                    <span className="font-medium">示例大学</span>
                    <span className="text-gray-400">2022.09 - 2026.07</span>
                  </div>
                  <div>计算机科学与技术 · 本科</div>
                  <div className="text-gray-500 mt-0.5">主修课程与成绩信息由候选人确认后填写</div>
                </div>
              </div>
              {/* 项目经历 */}
              <div>
                <div className="text-[10px] font-bold text-blue-600 border-b border-blue-200 pb-0.5 mb-1">项目经历</div>
                <div className="text-[9px]">
                  <div className="flex justify-between">
                    <span className="font-medium">课程项目示例</span>
                    <span className="text-gray-400">2024.09 - 2025.01</span>
                  </div>
                  <div className="text-gray-500">前端负责人 · 使用 React + TypeScript 开发</div>
                  <div className="text-gray-600 mt-0.5">
                    完成列表渲染与加载优化，<span className="text-success font-medium">效果数据待补充</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── 主组件 ──

export default function HomePage() {
  const { user } = useAuth();
  const navigate = useNavigate();

  const handlePrimaryCta = () => {
    if (user) {
      navigate("/resumes");
    } else {
      window.dispatchEvent(new Event("open-login-modal"));
    }
  };

  const scrollToFeatures = () => {
    document.getElementById("features")?.scrollIntoView({ behavior: "smooth" });
  };

  return (
    <div className="min-h-screen bg-[var(--color-bg)]">
      {/* 顶部导航（共享） */}
      <LandingNav />

      {/* Hero: product value first, with restrained visual hierarchy. */}
      <section className="relative">
        <div className="max-w-7xl mx-auto px-6 pt-24 pb-8 text-center">
          {/* 徽章 */}
          <div className="animate-fade-in-up">
            <Badge variant="brand" className="mb-6">
              <Compass size={12} aria-hidden="true" />
              面向校招与社招 · 从简历到复盘
            </Badge>
          </div>

          {/* 大标题：品牌渐变强调 */}
          <h1 className="text-4xl sm:text-5xl md:text-7xl font-bold text-[var(--color-text)] mb-6 display-tight leading-[1.08] animate-fade-in-up" style={{ animationDelay: "80ms" }}>
            让每次简历修改
            <br />
            <span className="text-[var(--color-primary)]">
              都能说明为什么
            </span>
          </h1>
          <p className="text-base md:text-xl text-[var(--color-text-secondary)] mb-10 max-w-2xl mx-auto animate-fade-in-up" style={{ animationDelay: "160ms" }}>
            导入简历，核对岗位证据，管理投递与面试复盘
            ——建议有来源，写回由你确认，重要资料可持续检索
          </p>

          {/* 双 CTA */}
          <div className="flex items-center justify-center gap-3 animate-fade-in-up" style={{ animationDelay: "240ms" }}>
            <Button size="lg" onClick={handlePrimaryCta} iconRight={<ArrowRight size={18} strokeWidth={2.25} aria-hidden="true" />}>
              {user ? "我的简历" : "开始使用"}
            </Button>
            <Button size="lg" variant="secondary" onClick={scrollToFeatures}>
              查看功能
            </Button>
          </div>

          {/* 信任数据 */}
          <div className="flex items-center justify-center gap-8 sm:gap-14 mt-12 animate-fade-in-up" style={{ animationDelay: "320ms" }}>
            {HERO_STATS.map((s) => (
              <div key={s.label} className="text-center">
                <div className="text-2xl sm:text-3xl font-bold text-[var(--color-text)] display-tight tabular-nums">{s.value}</div>
                <div className="text-[11px] text-[var(--color-text-muted)] mt-1">{s.label}</div>
              </div>
            ))}
          </div>
        </div>
        <ProductMockup />
      </section>

      {/* 功能简介：6 格 Bento */}
      <section id="features" className="max-w-6xl mx-auto px-6 py-24 scroll-mt-16">
        <div className="grid gap-3 md:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)] md:items-end mb-10">
          <h2 className="text-3xl md:text-4xl font-bold text-[var(--color-text)] display-tight">
            一套连贯的求职工作流
          </h2>
          <p className="text-[var(--color-text-muted)] text-sm md:text-right">
            核心任务做深，辅助功能保持可用；所有关键修改都留给用户确认
          </p>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 border-y border-[var(--color-border)]">
          {FEATURES.map((item, i) => (
            <div
              key={item.title}
              className={`group flex gap-4 py-6 sm:px-5 animate-fade-in-up ${
                i < FEATURES.length - 2 ? "border-b border-[var(--color-border)]" : ""
              } ${i % 2 === 0 ? "md:border-r md:border-[var(--color-border)] md:pr-8" : "md:pl-8"}`}
              style={{ animationDelay: `${i * 80}ms` }}
            >
              <div className="flex h-9 w-9 shrink-0 items-center justify-center text-brand">
                <item.icon size={20} strokeWidth={1.8} aria-hidden="true" />
              </div>
              <div>
                <div className="mb-1 text-[10px] font-medium tabular-nums text-[var(--color-text-muted)]">
                  {String(i + 1).padStart(2, "0")}
                </div>
                <h3 className="text-base font-semibold text-[var(--color-text)] mb-1.5 display-tight">{item.title}</h3>
                <p className="text-sm text-[var(--color-text-muted)] leading-relaxed">{item.desc}</p>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* 三步工作流 */}
      <section className="max-w-6xl mx-auto px-6 pb-24">
        <h2 className="text-3xl md:text-4xl font-bold text-[var(--color-text)] mb-10 display-tight">
          三步形成可复用的求职材料
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-3 border-t border-[var(--color-border)]">
          {STEPS.map((item, i) => (
            <div
              key={item.step}
              className={`py-7 animate-fade-in-up ${i > 0 ? "md:border-l md:border-[var(--color-border)] md:pl-8" : ""} ${i < STEPS.length - 1 ? "border-b md:border-b-0 border-[var(--color-border)] md:pr-8" : ""}`}
              style={{ animationDelay: `${i * 120}ms` }}
            >
              <div className="flex items-center justify-between mb-6">
                <span className="text-3xl font-semibold tabular-nums text-[var(--color-text-muted)]">{item.step}</span>
                <item.icon size={20} strokeWidth={1.8} className="text-brand" aria-hidden="true" />
              </div>
              <h3 className="text-base font-semibold text-[var(--color-text)] mb-1.5 display-tight">{item.title}</h3>
              <p className="text-sm text-[var(--color-text-muted)] leading-relaxed">{item.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* 底部 CTA */}
      <section className="max-w-6xl mx-auto px-6 pb-24">
        <div className="grid gap-6 border-y border-[var(--color-border)] py-10 md:grid-cols-[1fr_auto] md:items-center">
          <div>
            <h2 className="text-3xl md:text-4xl font-bold text-[var(--color-text)] display-tight mb-3">从一份可核对的简历开始</h2>
            <p className="text-[var(--color-text-muted)] text-sm md:text-base max-w-xl">
              上传现有简历或从结构化表单开始。先确认事实，再诊断、匹配岗位和跟踪投递。
            </p>
          </div>
          <Button
            size="lg"
            onClick={handlePrimaryCta}
            iconRight={<ArrowRight size={18} strokeWidth={2.25} aria-hidden="true" />}
          >
            {user ? "进入工作台" : "开始使用"}
          </Button>
        </div>
      </section>

      {/* C2: 信任合规页脚 */}
      <footer className="border-t border-black/5 py-6">
        <div className="max-w-6xl mx-auto px-6 flex flex-col sm:flex-row items-center justify-between gap-3 text-xs text-[var(--color-text-muted)]">
          <span>© 2026 轻舟简历</span>
          <div className="flex items-center gap-5">
            <Link to="/privacy" className="inline-flex min-h-11 items-center hover:text-[var(--color-text)] transition-colors">
              隐私政策
            </Link>
            <Link to="/terms" className="inline-flex min-h-11 items-center hover:text-[var(--color-text)] transition-colors">
              用户协议
            </Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
