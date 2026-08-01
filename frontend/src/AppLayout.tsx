import { useState, useMemo, lazy, Suspense, type ReactNode } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { ChatCircleDots, PencilSimpleLine } from "@phosphor-icons/react";
import { useAuth } from "./context/AuthContext";
import Navbar from "./components/Navbar";
import Sidebar from "./components/Sidebar";
import SessionExpiredDialog from "./components/SessionExpiredDialog";

// 惰性加载 — 首次切换到对应 tab 时才加载组件代码
const QAPage = lazy(() => import("./pages/QAPage"));
const BuilderPage = lazy(() =>
  import("./pages/BuilderPage").then((m) => ({ default: m.BuilderPage })),
);

/** Tab 内容懒加载 fallback */
function TabLoader() {
  return (
    <div className="flex-1 flex items-center justify-center text-[var(--color-text-muted)] text-sm">
      <span className="inline-block w-4 h-4 rounded-full border-2 border-indigo-400 border-t-transparent animate-spin mr-2" />
      加载中...
    </div>
  );
}

type TabId = "chat" | "edit";

interface TabDef {
  id: TabId;
  label: string;
  icon: typeof ChatCircleDots;
  disabled?: boolean;
}

interface AppLayoutProps {
  /** 通用布局内容；/resumes/:id 路由无 children，仅用 showSidebar 模式 */
  children?: ReactNode;
  /** 是否显示左侧 Sidebar（仅 /resumes/:id 路由开启） */
  showSidebar?: boolean;
}

/**
 * T20: AppLayout — 全局布局壳。
 *
 * 结构：
 * ┌──────────────────────────────────────────┐
 * │              Navbar (top)                │
 * ├──────────┬───────────────────────────────┤
 * │          │  Tab Bar (聊天 | 编辑)         │
 * │ Sidebar  ├───────────────────────────────┤
 * │ (left)   │  Tab Content (QAPage / Builder)│
 * │          │                               │
 * └──────────┴───────────────────────────────┘
 *
 * Tab 惰性挂载 + 保状态：首次切换到某 tab 时才渲染其内容，
 * 之后通过 CSS display:none 隐藏非活跃 tab，
 * 切换时不触发 unmount → Agent 流/对话状态不丢失。
 */
export default function AppLayout({ children, showSidebar = false }: AppLayoutProps) {
  const { sessionDialog, handleSessionGoLogin } = useAuth();
  const params = useParams<{ id: string }>();
  const activeResumeId = params.id ? Number(params.id) : undefined;

  // T20: Tab 状态 — 仅在 showSidebar 时使用
  // 支持 URL query `?tab=edit` 初始化为编辑页（新建简历后直达编辑）；useState 初始化器只在首次 mount 求值一次
  const [searchParams] = useSearchParams();
  const initialTab: TabId = searchParams.get("tab") === "edit" ? "edit" : "chat";
  const [activeTab, setActiveTab] = useState<TabId>(initialTab);
  // 惰性挂载：仅首次切换到某 tab 时才渲染其内容，之后保状态
  const [mountedTabs, setMountedTabs] = useState<Set<TabId>>(() => new Set([initialTab]));

  const handleTabChange = (tabId: TabId) => {
    setActiveTab(tabId);
    setMountedTabs((prev) => {
      if (prev.has(tabId)) return prev;
      const next = new Set(prev);
      next.add(tabId);
      return next;
    });
  };

  // Tab 配置
  const tabs = useMemo<TabDef[]>(
    () => [
      { id: "chat", label: "聊天", icon: ChatCircleDots },
      { id: "edit", label: "编辑", icon: PencilSimpleLine },
    ],
    [],
  );

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      <Navbar />

      {showSidebar ? (
        <div className="flex flex-1 overflow-hidden">
          {/* 左侧 Sidebar */}
          <Sidebar activeResumeId={activeResumeId} />

          {/* 右侧主区：Tab 栏 + 内容 */}
          <div className="flex-1 flex flex-col overflow-hidden">
            {/* Tab 栏 */}
            <div className="shrink-0 flex items-center gap-1 px-4 py-2 border-b border-[var(--color-border)] bg-[var(--color-bg)]">
              {tabs.map((tab) => {
                const Icon = tab.icon;
                const isActive = activeTab === tab.id;
                return (
                  <button
                    key={tab.id}
                    onClick={() => !tab.disabled && handleTabChange(tab.id)}
                    disabled={tab.disabled}
                    className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium
                      transition-all cursor-pointer
                      ${isActive
                        ? "bg-indigo-500/15 text-indigo-300 border border-indigo-500/30"
                        : "text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)] hover:bg-white/5 border border-transparent"
                      }
                      ${tab.disabled ? "opacity-40 cursor-not-allowed" : ""}`}
                    aria-label={tab.label}
                    aria-selected={isActive}
                    role="tab"
                  >
                    <Icon size={14} weight={isActive ? "fill" : "regular"} aria-hidden="true" />
                    {tab.label}
                    {tab.disabled && (
                      <span className="text-[9px] text-[var(--color-text-muted)] ml-0.5">即将</span>
                    )}
                  </button>
                );
              })}
            </div>

            {/* Tab 内容 — 惰性挂载 + CSS display 保状态 */}
            {/* 聊天 tab：默认挂载，QAPage 内部管理所有状态 */}
            {mountedTabs.has("chat") && (
              <div
                style={{ display: activeTab === "chat" ? "flex" : "none" }}
                className="flex-1 flex flex-col overflow-hidden"
              >
                <Suspense fallback={<TabLoader />}>
                  <QAPage />
                </Suspense>
              </div>
            )}

            {/* 编辑 tab：首次切换才挂载，T29 BuilderPage — 三栏 UI + 模块表单 + 预览 */}
            {mountedTabs.has("edit") && (
              <div
                style={{ display: activeTab === "edit" ? "flex" : "none" }}
                className="flex-1 flex-col overflow-hidden"
              >
                <Suspense fallback={<TabLoader />}>
                  {activeResumeId ? (
                    <BuilderPage resumeId={activeResumeId} />
                  ) : (
                    <div className="flex-1 flex flex-col items-center justify-center text-center px-6">
                      <p className="text-sm text-[var(--color-text-muted)]">
                        请先选择一份简历
                      </p>
                    </div>
                  )}
                </Suspense>
              </div>
            )}
          </div>
        </div>
      ) : (
        <div className="flex-1 overflow-auto">{children}</div>
      )}

      <SessionExpiredDialog
        open={sessionDialog !== null}
        onGoLogin={handleSessionGoLogin}
      />
    </div>
  );
}
