import { useState, type ReactNode } from "react";
import { useAuth } from "./context/AuthContext";
import { AppChatProvider } from "./context/AppChatContext";
import Sidebar from "./components/Sidebar";
import SessionExpiredDialog from "./components/SessionExpiredDialog";

interface AppLayoutProps {
  children?: ReactNode;
}

/**
 * AppLayout — 全局布局壳。
 *
 * 结构：
 * ┌──────────┬───────────────────────────────────┐
 * │          │                                   │
 * │ Sidebar  │  Main Content (children)          │
 * │ (left)   │                                   │
 * │          │                                   │
 * └──────────┴───────────────────────────────────┘
 *
 * Sidebar 包含：导航菜单 + 对话历史 + 底部用户信息
 */
export default function AppLayout({ children }: AppLayoutProps) {
  const { sessionDialog, handleSessionGoLogin } = useAuth();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  return (
    <AppChatProvider>
      <div className="flex h-screen overflow-hidden">
        {/* 左侧导航栏 */}
        <Sidebar
          collapsed={sidebarCollapsed}
          onToggleCollapse={() => setSidebarCollapsed((v) => !v)}
        />

        {/* 右侧主内容区 */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {children}
        </div>

        {/* 全局悬浮 AI 面板（根据路由切换内容） */}
      </div>

      <SessionExpiredDialog
        open={sessionDialog !== null}
        onGoLogin={handleSessionGoLogin}
      />
    </AppChatProvider>
  );
}
