import { useState, useCallback, type ReactNode } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import {
  Sparkle,
  X,
  PaperPlaneRight,
  FileText,
  PencilSimple,
  Target,
  Microphone,
  Translate,
} from "@phosphor-icons/react";

interface FloatingAIPanelProps {
  /** 是否在 Agent 聊天页（路由 /qa 时不显示展开面板） */
  isAgentPage?: boolean;
}

interface QuickAction {
  icon: ReactNode;
  label: string;
  /** 点击后传递给 Agent 页（/）的问题，Agent 页通过 location.state.question 接收 */
  question: string;
}

/* ── 各路由对应的快捷操作 ── */

// /resumes：简历管理
const RESUMES_ACTIONS: QuickAction[] = [
  { icon: <FileText size={18} weight="duotone" />, label: "帮我写简历", question: "帮我写一份专业的简历" },
  { icon: <PencilSimple size={18} weight="duotone" />, label: "帮我优化简历", question: "帮我优化我的简历" },
  { icon: <Target size={18} weight="duotone" />, label: "帮我分析职业发展方向", question: "帮我分析我的职业发展方向" },
  { icon: <Microphone size={18} weight="duotone" />, label: "帮我做模拟面试", question: "帮我做一次模拟面试" },
];

// /resumes/:id/edit：简历编辑
const RESUME_EDIT_ACTIONS: QuickAction[] = [
  { icon: <PencilSimple size={18} weight="duotone" />, label: "优化当前模块", question: "帮我优化当前正在编辑的简历模块" },
  { icon: <FileText size={18} weight="duotone" />, label: "检查简历格式", question: "帮我检查这份简历的格式是否规范" },
  { icon: <Translate size={18} weight="duotone" />, label: "改写薄弱部分", question: "帮我改写简历中表达薄弱的部分" },
];

// /qa（Agent 聊天页）：不展示悬浮面板（Agent 页已有完整对话界面）
// （移除 AGENT_TAGS，Agent 页不再渲染 FAB）

/** 快捷操作行按钮 */
function QuickActionButton({
  icon,
  label,
  onClick,
}: {
  icon: ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-center gap-3 rounded-[10px] px-3 py-2.5 text-left text-sm text-[var(--color-text)] transition-colors hover:bg-[var(--color-bg-secondary)]"
    >
      <span className="flex-shrink-0 text-brand">{icon}</span>
      <span>{label}</span>
    </button>
  );
}

/**
 * FloatingAIPanel — 全局悬浮 AI 面板。
 *
 * 在所有页面（登录页除外）右下角显示一个圆形渐变按钮；点击后根据当前路由
 * 展示不同的上下文快捷操作，点击快捷操作会导航到 Agent 聊天页（/）并
 * 通过 location.state.question 传递问题。
 *
 * 路由 → 内容：
 *  - /                  Agent 聊天页：不展开完整面板，仅显示快捷标签
 *  - /resumes           简历管理：4 个快捷操作 + "更多AI用法"
 *  - /resumes/:id/edit  简历编辑：3 个快捷操作
 *  - 其他               通用 AI 问候 + 输入框
 *
 * 集成：在 AppLayout 中渲染 <FloatingAIPanel /> 即可全局生效；登录为全局弹窗
 * 不经过 AppLayout 自然不显示（组件内对 /forgot-password 做了兜底）。
 */
export default function FloatingAIPanel({ isAgentPage }: FloatingAIPanelProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [inputValue, setInputValue] = useState("");

  const navigate = useNavigate();
  const location = useLocation();
  const pathname = location.pathname;

  // 路由匹配（若实际路由表有差异，调整下列正则 / 判定即可）
  const isAgent = isAgentPage ?? pathname === "/qa";
  const isResumesList = pathname === "/resumes";
  const isResumeEdit = /^\/resumes\/[^/]+\/edit$/.test(pathname);

  // 点击快捷操作：导航到 Agent 页并传递问题
  const handleQuickAction = useCallback(
    (question: string) => {
      navigate("/qa", { state: { question } });
      setIsOpen(false);
    },
    [navigate],
  );

  // 通用输入框：回车 / 点击发送
  const handleSendInput = useCallback(() => {
    const question = inputValue.trim();
    if (!question) return;
    navigate("/qa", { state: { question } });
    setInputValue("");
    setIsOpen(false);
  }, [inputValue, navigate]);

  // 忘记密码页不渲染（兜底；实际由父组件是否挂载控制）
  if (pathname === "/forgot-password") {
    return null;
  }

  // Agent 聊天页（/qa）不渲染悬浮面板 — Agent 页已有完整的对话 + 输入界面
  if (isAgent) {
    return null;
  }

  const contextLabel = isResumesList
    ? "简历管理"
    : isResumeEdit
      ? "简历编辑"
      : "通用助手";

  const renderBody = (): ReactNode => {
    // 其他路由：通用 AI 问候 + 输入框
    if (!isResumesList && !isResumeEdit) {
      return (
        <div className="flex flex-col gap-3 p-2">
          <div className="flex items-start gap-2">
            <Sparkle size={18} weight="fill" className="mt-0.5 flex-shrink-0 text-brand" />
            <p className="text-sm leading-relaxed text-[var(--color-text-secondary)]">
              你好！我是你的 AI 助手，有什么可以帮你的吗？
            </p>
          </div>
          <div className="flex items-center gap-2 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-secondary)] px-2 py-1.5 transition-all focus-within:border-brand/40 focus-within:ring-4 focus-within:ring-brand/15">
            <input
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleSendInput();
              }}
              placeholder="输入你的问题..."
              aria-label="向 AI 助手提问"
              className="flex-1 bg-transparent text-sm text-[var(--color-text)] outline-none placeholder:text-[var(--color-text-muted)]"
            />
            <button
              type="button"
              onClick={handleSendInput}
              aria-label="发送"
              className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full bg-brand text-white transition-transform hover:scale-105 active:scale-95"
            >
              <PaperPlaneRight size={15} weight="bold" />
            </button>
          </div>
        </div>
      );
    }

    const actions = isResumesList
      ? RESUMES_ACTIONS
      : RESUME_EDIT_ACTIONS;

    return (
      <div className="flex flex-col p-1">
        {actions.map((action) => (
          <QuickActionButton
            key={action.label}
            icon={action.icon}
            label={action.label}
            onClick={() => handleQuickAction(action.question)}
          />
        ))}

        {/* /resumes 列表页额外提供"更多AI用法"入口 */}
        {isResumesList && (
          <button
            type="button"
            onClick={() => handleQuickAction("请介绍一下你还能帮我做哪些事情？")}
            className="mt-1 flex items-center justify-center gap-2 rounded-[10px] border border-dashed border-[var(--color-border)] px-3 py-2 text-sm text-[var(--color-text-secondary)] transition-colors hover:bg-[var(--color-bg-secondary)]"
          >
            <Sparkle size={16} weight="fill" className="text-brand" />
            更多AI用法
          </button>
        )}
      </div>
    );
  };

  return (
    <>
      {/* 收起 / 展开切换按钮（圆形品牌蓝 FAB） */}
      <button
        type="button"
        onClick={() => setIsOpen((v) => !v)}
        aria-label={isOpen ? "关闭 AI 助手" : "打开 AI 助手"}
        className="fixed bottom-6 right-6 z-50 flex h-12 w-12 items-center justify-center rounded-full bg-brand text-white shadow-lg shadow-brand/25 transition-all hover:scale-105 hover:shadow-xl hover:shadow-brand/30 active:scale-95"
      >
        {isOpen ? <X size={22} weight="bold" /> : <Sparkle size={22} weight="fill" />}
      </button>

      {/* 非 Agent 页：展开为浮动面板 */}
      {isOpen && (
        <div className="fixed bottom-24 right-6 z-50 w-72 animate-fade-in-up overflow-hidden rounded-2xl border border-[var(--color-border)] bg-white/90 backdrop-blur-xl text-[var(--color-text)] shadow-2xl">
          {/* 头部 */}
          <div className="flex items-center gap-2 border-b border-[var(--color-border)] px-4 py-3">
            <Sparkle size={18} weight="fill" className="flex-shrink-0 text-brand" />
            <div className="flex flex-col leading-tight">
              <span className="text-sm font-semibold">AI 助手</span>
              <span className="text-xs text-[var(--color-text-muted)]">{contextLabel}</span>
            </div>
          </div>

          {/* 内容区（随路由变化） */}
          <div className="py-1">{renderBody()}</div>
        </div>
      )}
    </>
  );
}
