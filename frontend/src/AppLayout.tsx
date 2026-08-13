import { useEffect, useState, type ReactNode } from "react";
import { useAuth } from "./context/AuthContext";
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
  const [mobile, setMobile] = useState(() => window.matchMedia("(max-width: 639px)").matches);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(
    () => window.matchMedia("(max-width: 639px)").matches,
  );

  useEffect(() => {
    const media = window.matchMedia("(max-width: 639px)");
    const sync = () => {
      setMobile(media.matches);
      if (media.matches) setSidebarCollapsed(true);
    };
    media.addEventListener("change", sync);
    return () => media.removeEventListener("change", sync);
  }, []);

  return (
    <>
      <div className="relative flex h-screen overflow-hidden">
        {mobile && !sidebarCollapsed && (
          <button
            type="button"
            className="fixed inset-0 z-30 bg-black/35"
            aria-label="关闭侧边栏"
            onClick={() => setSidebarCollapsed(true)}
          />
        )}
        {/* 左侧导航栏 */}
        <Sidebar
          collapsed={sidebarCollapsed}
          mobile={mobile}
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
    </>
  );
}
