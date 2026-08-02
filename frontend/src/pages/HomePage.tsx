/**
 * HomePage — 网站首页（纯展示介绍页）
 *
 * 结构：共享顶部导航（LandingNav）+ Hero（标题/CTA/产品展示模型）+ 功能简介。
 * 内容页（模板/范文/攻略等）由各自独立页面直接展示，首页不做内容承载。
 */

import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import LandingNav from "../components/LandingNav";
import { Sparkle, ArrowRight, Robot, FileText, Target } from "@phosphor-icons/react";

// ── 产品展示模型 ──

function ProductMockup() {
  return (
    <div className="relative max-w-5xl mx-auto mt-10 px-4">
      {/* 外层容器：模拟浏览器窗口 */}
      <div className="rounded-[24px] overflow-hidden border border-[var(--color-border)] bg-white/80 backdrop-blur-xl shadow-2xl shadow-black/10">
        {/* 浏览器顶栏 */}
        <div className="flex items-center gap-2 px-4 py-2.5 bg-[var(--color-bg-secondary)] border-b border-[var(--color-border)]">
          <div className="flex gap-1.5">
            <div className="w-2.5 h-2.5 rounded-full bg-red-400/70" />
            <div className="w-2.5 h-2.5 rounded-full bg-yellow-400/70" />
            <div className="w-2.5 h-2.5 rounded-full bg-green-400/70" />
          </div>
          <div className="flex-1 flex justify-center">
            <div className="flex items-center gap-3 text-[10px] text-[var(--color-text-muted)]">
              <span className="px-3 py-0.5 rounded-full bg-brand/10 text-brand font-medium">Agent</span>
              <span className="px-3 py-0.5 rounded-full hover:bg-[var(--color-bg-secondary)] cursor-pointer">简历构建</span>
            </div>
          </div>
        </div>

        {/* 内容区：左 Agent + 右 简历预览 */}
        <div className="flex min-h-[340px] md:min-h-[420px]">
          {/* 左侧：Agent 聊天 */}
          <div className="flex-1 border-r border-[var(--color-border)] p-4 flex flex-col gap-3">
            {/* 系统消息 */}
            <div className="flex gap-2">
              <div className="w-6 h-6 rounded-full bg-brand/10 flex items-center justify-center shrink-0">
                <Sparkle size={12} weight="fill" className="text-brand" />
              </div>
              <div className="bg-[var(--color-bg-secondary)] rounded-xl rounded-tl-sm px-3 py-2 text-xs text-[var(--color-text-secondary)] leading-relaxed max-w-[85%]">
                你好！我是你的 AI 简历助手。请先告诉我你的基本信息，我来帮你构建简历。
              </div>
            </div>
            {/* 用户消息 */}
            <div className="flex gap-2 justify-end">
              <div className="bg-brand text-white rounded-xl rounded-tr-sm px-3 py-2 text-xs leading-relaxed max-w-[85%]">
                我是清华大学计算机专业的学生，GPA 3.7/4.0
              </div>
            </div>
            {/* 系统回复 */}
            <div className="flex gap-2">
              <div className="w-6 h-6 rounded-full bg-brand/10 flex items-center justify-center shrink-0">
                <Sparkle size={12} weight="fill" className="text-brand" />
              </div>
              <div className="bg-[var(--color-bg-secondary)] rounded-xl rounded-tl-sm px-3 py-2 text-xs text-[var(--color-text-secondary)] leading-relaxed max-w-[85%]">
                太棒了！第一段教育经历填写完成。要不要添加更多教育经历？
              </div>
            </div>
            {/* 快捷操作 */}
            <div className="flex flex-wrap gap-2 mt-1">
              {["是，添加教育经历", "否，继续下一步"].map((text) => (
                <div key={text} className="px-3 py-1.5 rounded-full border border-brand/30 text-[10px] text-brand bg-brand/5">
                  {text}
                </div>
              ))}
            </div>
          </div>

          {/* 右侧：简历预览 */}
          <div className="hidden md:block flex-1 p-4 bg-[var(--color-bg)]">
            <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-5 h-full text-gray-800 text-[10px] leading-relaxed">
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
              {/* 技能 */}
              <div className="mb-2">
                <div className="text-[10px] font-bold text-blue-600 border-b border-blue-200 pb-0.5 mb-1">技能</div>
                <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-[9px]">
                  <div><span className="font-medium">前端技术</span><br/>React, TypeScript, HTML/CSS</div>
                  <div><span className="font-medium">工程工具</span><br/>Webpack, Git, npm</div>
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
                  <div className="text-gray-500">前端负责人</div>
                  <div className="text-gray-600 mt-0.5">使用 React + TypeScript 开发跨平台小程序，实现10+功能模块</div>
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

  return (
    <div className="min-h-screen bg-[var(--color-bg)]">
      {/* 顶部导航（共享） */}
      <LandingNav />

      {/* Hero（Aurora 氛围由全局背景光球提供） */}
      <section className="relative">
        <div className="max-w-7xl mx-auto px-6 pt-24 pb-8 text-center">
          <h1 className="text-5xl md:text-6xl font-bold text-[var(--color-text)] mb-5 display-tight leading-[1.05]">
            AI简历
          </h1>
          <p className="text-lg md:text-xl text-[var(--color-text-secondary)] mb-10 max-w-xl mx-auto">
            AI帮你打造高通过率简历，助你拿下心仪 offer
          </p>
          {user ? (
            <button
              onClick={() => navigate("/resumes")}
              className="inline-flex items-center gap-2 px-8 py-3.5 rounded-full text-base font-semibold text-white
                bg-brand hover:bg-[#0077ed] hover:scale-[1.02] active:scale-[0.98]
                shadow-lg shadow-brand/30 transition-all duration-300 cursor-pointer"
            >
              我的简历 <ArrowRight size={18} weight="bold" />
            </button>
          ) : (
            <button
              onClick={() => window.dispatchEvent(new Event("open-login-modal"))}
              className="inline-flex items-center gap-2 px-8 py-3.5 rounded-full text-base font-semibold text-white
                bg-brand hover:bg-[#0077ed] hover:scale-[1.02] active:scale-[0.98]
                shadow-lg shadow-brand/30 transition-all duration-300 cursor-pointer"
            >
              开始使用 <ArrowRight size={18} weight="bold" />
            </button>
          )}
        </div>
        <ProductMockup />
      </section>

      {/* 功能简介：Bento 卡片 */}
      <section className="max-w-6xl mx-auto px-6 py-24">
        <h2 className="text-3xl md:text-4xl font-bold text-center text-[var(--color-text)] mb-4 display-tight">
          一站式求职，从简历开始
        </h2>
        <p className="text-center text-[var(--color-text-muted)] text-sm mb-12">
          三大能力，覆盖简历构建、优化与求职全流程
        </p>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
          {[
            { icon: Robot, title: "AI 智能对话", desc: "与 AI Agent 实时对话，一步步引导你完成简历构建与优化" },
            { icon: FileText, title: "专业简历编辑器", desc: "模板化编辑器，模块自由增删排序，一键预览与导出" },
            { icon: Target, title: "求职全程护航", desc: "校招信息、投递跟踪、面试模拟，求职链路一站打通" },
          ].map((item, i) => (
            <div
              key={item.title}
              className="glass-card p-8 hover:-translate-y-1 hover:shadow-xl hover:shadow-black/5 transition-all duration-400 animate-fade-in-up"
              style={{ animationDelay: `${i * 120}ms` }}
            >
              <div className="w-12 h-12 rounded-2xl bg-brand/10 flex items-center justify-center mb-5">
                <item.icon size={22} weight="duotone" className="text-brand" />
              </div>
              <h3 className="text-lg font-semibold text-[var(--color-text)] mb-2 display-tight">{item.title}</h3>
              <p className="text-sm text-[var(--color-text-muted)] leading-relaxed">{item.desc}</p>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
