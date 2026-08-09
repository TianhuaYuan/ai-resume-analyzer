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
import {
  Sparkle,
  ArrowRight,
  ChatCircleDots,
  FileText,
  Target,
  SealCheck,
  Briefcase,
  Microphone,
  UploadSimple,
  Compass,
} from "@phosphor-icons/react";

// ── Hero 信任数据 ──

const HERO_STATS = [
  { value: "6+", label: "智能分析维度" },
  { value: "30s", label: "快速简历诊断" },
  { value: "3 步", label: "简历→投递闭环" },
];

// ── Bento 功能卡 ──

interface Feature {
  icon: typeof ChatCircleDots;
  title: string;
  desc: string;
  /** icon 底色 + 文字色（浅色 alpha，双主题可读） */
  tint: string;
}

const FEATURES: Feature[] = [
  { icon: ChatCircleDots, title: "AI 智能对话", desc: "与 AI Agent 实时对话，一步步引导完成简历构建与优化", tint: "bg-brand/10 text-brand" },
  { icon: FileText, title: "专业简历编辑器", desc: "Tiptap 所见即所得，模块自由增删排序，一键预览与导出", tint: "bg-sky-500/10 text-sky-500" },
  { icon: SealCheck, title: "ATS 深度诊断", desc: "多维度评分定位简历短板，关键词命中与结构优化一目了然", tint: "bg-success-soft text-success" },
  { icon: Briefcase, title: "校招情报实时同步", desc: "校招/社招岗位信息聚合，投递跟踪与截止提醒一站掌握", tint: "bg-warning-soft text-warning" },
  { icon: Microphone, title: "面试模拟指导", desc: "基于你的简历生成模拟面试，针对性提问并给出回答建议", tint: "bg-purple-500/10 text-purple-500" },
  { icon: Target, title: "求职全程护航", desc: "从简历到投递到复盘，求职链路完整闭环，Offer 尽在掌握", tint: "bg-rose-500/10 text-rose-500" },
];

// ── 三步工作流 ──

const STEPS = [
  { icon: UploadSimple, step: "01", title: "上传简历", desc: "PDF / DOCX 一键上传，自动解析为结构化内容" },
  { icon: Sparkle, step: "02", title: "AI 诊断优化", desc: "多维度评分 + 针对性建议，逐条接受或拒绝" },
  { icon: Briefcase, step: "03", title: "投递校招", desc: "匹配校招岗位，跟踪投递进度，备战面试" },
];

// ── 产品展示模型（浏览器窗口 + Agent 聊天 + 简历预览） ──

function ProductMockup() {
  return (
    <div className="relative max-w-5xl mx-auto mt-12 px-4">
      {/* 外层容器：模拟浏览器窗口 */}
      <div className="rounded-[24px] overflow-hidden border border-[var(--color-border)] bg-white/80 backdrop-blur-xl shadow-2xl shadow-black/10">
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
                <Compass size={12} weight="fill" className="text-brand" />
              </div>
              <div className="bg-[var(--color-bg-secondary)] rounded-list rounded-tl-sm px-3 py-2 text-xs text-[var(--color-text-secondary)] leading-relaxed max-w-[85%]">
                你好！我是你的 AI 简历助手。请先告诉我你的基本信息，我来帮你构建简历。
              </div>
            </div>
            {/* 用户消息 */}
            <div className="flex gap-2 justify-end">
              <div className="bg-brand text-white rounded-list rounded-tr-sm px-3 py-2 text-xs leading-relaxed max-w-[85%]">
                我是清华大学计算机专业的学生，GPA 3.7/4.0
              </div>
            </div>
            {/* ATS 诊断卡（模拟实时分析结果） */}
            <div className="flex gap-2">
              <div className="w-6 h-6 rounded-full bg-brand/10 flex items-center justify-center shrink-0">
                <Compass size={12} weight="fill" className="text-brand" />
              </div>
              <div className="flex-1 max-w-[85%] bg-white/70 dark:bg-white/5 border border-[var(--color-border)] rounded-list p-3">
                <div className="flex items-center justify-between text-[10px] mb-1.5">
                  <span className="text-[var(--color-text-muted)] font-medium">ATS 匹配度</span>
                  <span className="text-brand font-semibold tabular-nums">92%</span>
                </div>
                <div className="h-1.5 rounded-full bg-[var(--color-bg-secondary)] overflow-hidden">
                  <div className="h-full w-[92%] rounded-full bg-gradient-to-r from-brand to-[#5856d6]" />
                </div>
                <div className="flex flex-wrap gap-1 mt-2">
                  {["关键词命中", "结构清晰", "量化突出"].map((t) => (
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
                <Compass size={12} weight="fill" className="text-brand" />
              </div>
              <div className="bg-[var(--color-bg-secondary)] rounded-list rounded-tl-sm px-3 py-2 text-xs text-[var(--color-text-secondary)] leading-relaxed max-w-[85%]">
                太棒了！诊断完成，建议补充 2 个量化指标，我来帮你优化。
              </div>
            </div>
            {/* 打字指示器（Open WebUI 风格两粒圆点） */}
            <div className="flex gap-2">
              <div className="w-6 h-6 rounded-full bg-brand/10 flex items-center justify-center shrink-0">
                <Compass size={12} weight="fill" className="text-brand" />
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
                <div className="text-[10px] text-gray-500 mt-0.5">前端开发实习生</div>
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
                    <span className="font-medium">清华大学</span>
                    <span className="text-gray-400">2022.09 - 2026.07</span>
                  </div>
                  <div>计算机科学与技术 · 本科</div>
                  <div className="text-gray-500 mt-0.5">GPA: 3.7/4.0，专业排名前15%</div>
                </div>
              </div>
              {/* 项目经历 */}
              <div>
                <div className="text-[10px] font-bold text-blue-600 border-b border-blue-200 pb-0.5 mb-1">项目经历</div>
                <div className="text-[9px]">
                  <div className="flex justify-between">
                    <span className="font-medium">XX项目名称</span>
                    <span className="text-gray-400">2024.09 - 2025.01</span>
                  </div>
                  <div className="text-gray-500">前端负责人 · 使用 React + TypeScript 开发</div>
                  <div className="text-gray-600 mt-0.5">
                    实现 10+ 功能模块，<span className="text-success font-medium">性能提升 30%</span>
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

      {/* Hero（Aurora 氛围由全局背景光球提供） */}
      <section className="relative">
        <div className="max-w-7xl mx-auto px-6 pt-24 pb-8 text-center">
          {/* 徽章 */}
          <div className="animate-fade-in-up">
            <Badge variant="brand" className="mb-6">
              <Sparkle size={12} weight="fill" aria-hidden="true" />
              AI 驱动 · 校招/社招数据实时同步
            </Badge>
          </div>

          {/* 大标题：品牌渐变强调 */}
          <h1 className="text-5xl md:text-7xl font-bold text-[var(--color-text)] mb-6 display-tight leading-[1.05] animate-fade-in-up" style={{ animationDelay: "80ms" }}>
            AI 简历，帮你
            <br />
            <span className="bg-gradient-to-r from-[var(--color-primary)] to-[#5856d6] bg-clip-text text-transparent">
              拿下心仪 offer
            </span>
          </h1>
          <p className="text-lg md:text-xl text-[var(--color-text-secondary)] mb-10 max-w-2xl mx-auto animate-fade-in-up" style={{ animationDelay: "160ms" }}>
            智能诊断 + 专业编辑器 + 求职护航
            <br className="sm:hidden" />
            ——从简历到 offer 的一站式 AI 求职助手
          </p>

          {/* 双 CTA */}
          <div className="flex items-center justify-center gap-3 animate-fade-in-up" style={{ animationDelay: "240ms" }}>
            <Button size="lg" onClick={handlePrimaryCta} iconRight={<ArrowRight size={18} weight="bold" aria-hidden="true" />}>
              {user ? "我的简历" : "开始使用"}
            </Button>
            <Button size="lg" variant="secondary" onClick={scrollToFeatures}>
              了解 AI 能力
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
        <h2 className="text-3xl md:text-4xl font-bold text-center text-[var(--color-text)] mb-4 display-tight">
          一站式求职，从简历开始
        </h2>
        <p className="text-center text-[var(--color-text-muted)] text-sm mb-14">
          六大能力，覆盖简历构建、优化与求职全流程
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
          {FEATURES.map((item, i) => (
            <div
              key={item.title}
              className="group glass-card p-7 hover:-translate-y-1 hover:shadow-xl hover:shadow-black/5 transition-all duration-400 animate-fade-in-up"
              style={{ animationDelay: `${i * 80}ms` }}
            >
              <div className={`w-11 h-11 rounded-input flex items-center justify-center mb-5 transition-transform duration-300 group-hover:scale-110 ${item.tint}`}>
                <item.icon size={20} weight="duotone" aria-hidden="true" />
              </div>
              <h3 className="text-base font-semibold text-[var(--color-text)] mb-2 display-tight">{item.title}</h3>
              <p className="text-sm text-[var(--color-text-muted)] leading-relaxed">{item.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* 三步工作流 */}
      <section className="max-w-6xl mx-auto px-6 pb-24">
        <h2 className="text-3xl md:text-4xl font-bold text-center text-[var(--color-text)] mb-14 display-tight">
          三步拿到心仪 Offer
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-10 relative">
          {/* 连接线（md 以上显示） */}
          <div className="hidden md:block absolute top-8 left-[16.67%] right-[16.67%] h-px bg-gradient-to-r from-transparent via-brand/30 to-transparent" aria-hidden="true" />
          {STEPS.map((item, i) => (
            <div key={item.step} className="relative text-center animate-fade-in-up" style={{ animationDelay: `${i * 120}ms` }}>
              <div className="relative mx-auto w-16 h-16 rounded-full bg-white/80 dark:bg-[var(--color-bg-secondary)] border border-[var(--color-border)] shadow-lg shadow-black/5 flex items-center justify-center mb-5">
                <item.icon size={22} weight="duotone" className="text-brand" aria-hidden="true" />
                <span className="absolute -top-1.5 -right-1.5 w-6 h-6 rounded-full bg-brand text-white text-[10px] font-semibold flex items-center justify-center shadow-sm">
                  {item.step}
                </span>
              </div>
              <h3 className="text-base font-semibold text-[var(--color-text)] mb-1.5 display-tight">{item.title}</h3>
              <p className="text-sm text-[var(--color-text-muted)] leading-relaxed max-w-xs mx-auto">{item.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* 底部 CTA：品牌渐变卡片 */}
      <section className="max-w-6xl mx-auto px-6 pb-24">
        <div className="relative overflow-hidden rounded-modal bg-gradient-to-br from-[#0071e3] via-[#0a6cd6] to-[#5856d6] px-8 py-16 text-center text-white shadow-2xl shadow-brand/30">
          {/* 装饰光晕 */}
          <div className="absolute -top-24 -right-16 w-72 h-72 rounded-full bg-white/15 blur-3xl" aria-hidden="true" />
          <div className="absolute -bottom-24 -left-16 w-72 h-72 rounded-full bg-white/10 blur-3xl" aria-hidden="true" />
          <div className="relative">
            <h2 className="text-3xl md:text-4xl font-bold display-tight mb-4">现在就开始，让 AI 帮你写简历</h2>
            <p className="text-white/80 text-sm md:text-base mb-8 max-w-xl mx-auto">
              上传简历即可获得多维诊断与优化建议，全程 AI 护航，助你拿下心仪 offer
            </p>
            <Button
              size="lg"
              onClick={handlePrimaryCta}
              className="!bg-white !text-[#0071e3] hover:!bg-white/90 hover:!shadow-white/30"
              iconRight={<ArrowRight size={18} weight="bold" aria-hidden="true" />}
            >
              {user ? "进入工作台" : "免费开始使用"}
            </Button>
          </div>
        </div>
      </section>

      {/* C2: 信任合规页脚 */}
      <footer className="border-t border-black/5 py-6">
        <div className="max-w-6xl mx-auto px-6 flex flex-col sm:flex-row items-center justify-between gap-3 text-xs text-[var(--color-text-muted)]">
          <span>© 2026 AI 简历求职助手</span>
          <div className="flex items-center gap-5">
            <Link to="/privacy" className="hover:text-[var(--color-text)] transition-colors">
              隐私政策
            </Link>
            <Link to="/terms" className="hover:text-[var(--color-text)] transition-colors">
              用户协议
            </Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
