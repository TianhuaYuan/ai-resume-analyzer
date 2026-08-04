/**
 * LandingNav — 首页/内容页共享顶部导航（Apple 风格）。
 *
 * 浅色毛玻璃顶栏 + 品牌蓝胶囊按钮。登录使用全局 LoginModal 弹窗
 * （见 ./LoginModal），不再跳转独立 /login 页面。
 */

import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { CaretDown, EnvelopeSimple, User, Shield, Key, Gauge, SignOut, Sun } from "@phosphor-icons/react";
import { useTheme } from "../context/ThemeContext";
import { openLoginModal } from "./LoginModal";
import ChangePasswordDialog from "./ChangePasswordDialog";
import ChangeEmailDialog from "./ChangeEmailDialog";
import ChangeUsernameDialog from "./ChangeUsernameDialog";
import UsageDialog from "./UsageDialog";
import type { QuotaResponse } from "../api/qa";

// ── 导航项配置 ──

interface NavItem {
  key: string;
  label: string;
  route: string;
  requireAuth?: boolean;
}

const NAV_ITEMS: NavItem[] = [
  { key: "ai", label: "AI简历", route: "/qa", requireAuth: true },
  { key: "campus", label: "校招信息", route: "/campus" },
  { key: "social", label: "社招信息", route: "/social" },
  { key: "feedback", label: "用户反馈", route: "/feedback" },
];

// ── 顶部导航 ──

interface LandingNavProps {
  /** 当前高亮的导航 key（默认无高亮） */
  activeKey?: string;
}

export default function LandingNav({ activeKey }: LandingNavProps) {
  const { user, logout } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const navigate = useNavigate();

  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [passwordDialogOpen, setPasswordDialogOpen] = useState(false);
  const [emailDialogOpen, setEmailDialogOpen] = useState(false);
  const [usernameDialogOpen, setUsernameDialogOpen] = useState(false);
  const [usageDialogOpen, setUsageDialogOpen] = useState(false);
  const [quota, setQuota] = useState<QuotaResponse | null>(null);
  const userMenuRef = useRef<HTMLDivElement>(null);

  // 点击外部关闭用户菜单
  useEffect(() => {
    if (!userMenuOpen) return;
    const handler = (e: MouseEvent) => {
      if (userMenuRef.current && !userMenuRef.current.contains(e.target as Node)) {
        setUserMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [userMenuOpen]);

  // Token 用量
  useEffect(() => {
    const fetchQuota = () => {
      import("../api/qa")
        .then(({ getQuota }) => getQuota())
        .then((data) => setQuota(data))
        .catch(() => {});
    };
    fetchQuota();
    const interval = setInterval(fetchQuota, 30000);
    return () => clearInterval(interval);
  }, []);

  const handleNavClick = (item: NavItem) => {
    if (item.requireAuth && !user) {
      openLoginModal();
      return;
    }
    navigate(item.route);
  };

  const handleLogout = async () => {
    await logout();
    setUserMenuOpen(false);
  };

  return (
    <>
      <nav className="sticky top-0 z-30 bg-white/70 backdrop-blur-2xl border-b border-[var(--color-border)]">
        <div className="max-w-7xl mx-auto px-6 h-14 flex items-center gap-6">
          {/* Logo */}
          <button
            onClick={() => navigate("/")}
            className="flex items-center gap-2 shrink-0 cursor-pointer transition-transform duration-300 hover:scale-[1.02]"
          >
            <svg viewBox="0 0 64 64" className="w-7 h-7">
              <polygon points="32,6 54,18 32,30 10,18" fill="#F5C547" />
              <polygon points="10,18 32,30 32,54 10,42" fill="#38D4D4" />
              <polygon points="32,30 54,18 54,42 32,54" fill="#8B5CF6" />
            </svg>
            <span className="text-sm font-semibold text-[var(--color-text)] display-tight">
              轻舟简历
            </span>
          </button>

          {/* 导航项 */}
          <div className="flex items-center gap-0.5 overflow-x-auto">
            {NAV_ITEMS.map((item) => (
              <button
                key={item.key}
                onClick={() => handleNavClick(item)}
                className={`px-3 py-1.5 text-sm font-medium transition-all duration-300 cursor-pointer rounded-full whitespace-nowrap
                  ${activeKey === item.key
                    ? "text-brand bg-brand/10"
                    : "text-[var(--color-text-secondary)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-secondary)]"
                  }`}
              >
                {item.label}
              </button>
            ))}
          </div>

          {/* 右侧 */}
          <div className="flex-1" />
          <div className="flex items-center gap-3 shrink-0">
            {user ? (
              <div className="relative" ref={userMenuRef}>
                <button
                  onClick={() => setUserMenuOpen((v) => !v)}
                  className="flex items-center gap-2 px-2 py-1 rounded-full hover:bg-[var(--color-bg-secondary)] transition-colors cursor-pointer"
                >
                  <div className="w-7 h-7 rounded-full bg-brand flex items-center justify-center text-white text-xs font-semibold">
                    {user.username.charAt(0).toUpperCase()}
                  </div>
                  <span className="text-xs text-[var(--color-text-secondary)] hidden sm:inline">{user.username}</span>
                  <CaretDown size={12} className={`text-[var(--color-text-muted)] transition-transform duration-300 ${userMenuOpen ? "rotate-180" : ""}`} />
                </button>
                {userMenuOpen && (
                  <div className="absolute right-0 top-full mt-2 w-48 rounded-2xl bg-white/90 backdrop-blur-xl border border-[var(--color-border)] shadow-2xl shadow-black/10 py-1 z-50 animate-fade-in-down">
                    {/* Token 用量概览 */}
                    {quota?.enabled && (
                      <div className="px-3.5 py-2.5 border-b border-[var(--color-border)]">
                        <div className="flex items-center justify-between mb-1.5">
                          <span className="text-[10px] text-[var(--color-text-muted)]">今日用量</span>
                          <span className="text-[10px] font-medium text-[var(--color-text-secondary)] tabular-nums">
                            {quota.used.toLocaleString()} / {quota.limit.toLocaleString()}
                          </span>
                        </div>
                        <div className="h-1.5 rounded-full bg-[var(--color-bg-secondary)] overflow-hidden">
                          <div
                            className={`h-full rounded-full transition-all ${
                              quota.remaining < quota.limit * 0.1
                                ? "bg-red-500"
                                : quota.remaining < quota.limit * 0.3
                                  ? "bg-yellow-500"
                                  : "bg-brand"
                            }`}
                            style={{
                              width: `${Math.min(100, Math.round((quota.used / quota.limit) * 100))}%`,
                            }}
                          />
                        </div>
                      </div>
                    )}

                    {/* 管理后台 */}
                    {user.is_admin && (
                      <button
                        onClick={() => { navigate("/admin"); setUserMenuOpen(false); }}
                        className="w-full flex items-center gap-2.5 px-3.5 py-2 text-xs text-[var(--color-text-secondary)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-secondary)] cursor-pointer transition-colors"
                      >
                        <Shield size={14} weight="regular" aria-hidden="true" />
                        管理后台
                      </button>
                    )}

                    <div className="border-t border-[var(--color-border)] my-1" />

                    {/* 设置项 */}
                    <button
                      onClick={() => { setPasswordDialogOpen(true); setUserMenuOpen(false); }}
                      className="w-full flex items-center gap-2.5 px-3.5 py-2 text-xs text-[var(--color-text-secondary)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-secondary)] cursor-pointer transition-colors"
                    >
                      <Key size={14} weight="regular" aria-hidden="true" />
                      修改密码
                    </button>
                    <button
                      onClick={() => { setEmailDialogOpen(true); setUserMenuOpen(false); }}
                      className="w-full flex items-center gap-2.5 px-3.5 py-2 text-xs text-[var(--color-text-secondary)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-secondary)] cursor-pointer transition-colors"
                    >
                      <EnvelopeSimple size={14} weight="regular" aria-hidden="true" />
                      重新绑定邮箱
                    </button>
                    <button
                      onClick={() => { setUsernameDialogOpen(true); setUserMenuOpen(false); }}
                      className="w-full flex items-center gap-2.5 px-3.5 py-2 text-xs text-[var(--color-text-secondary)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-secondary)] cursor-pointer transition-colors"
                    >
                      <User size={14} weight="regular" aria-hidden="true" />
                      修改用户名
                    </button>
                    <button
                      onClick={() => { setUsageDialogOpen(true); setUserMenuOpen(false); }}
                      className="w-full flex items-center gap-2.5 px-3.5 py-2 text-xs text-[var(--color-text-secondary)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-secondary)] cursor-pointer transition-colors"
                    >
                      <Gauge size={14} weight="regular" aria-hidden="true" />
                      用量统计
                    </button>

                    {/* 主题切换 */}
                    <button
                      onClick={toggleTheme}
                      className="w-full flex items-center gap-2.5 px-3.5 py-2 text-xs text-[var(--color-text-secondary)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-secondary)] cursor-pointer transition-colors"
                    >
                      <Sun size={14} weight={theme === "dark" ? "fill" : "regular"} aria-hidden="true" />
                      {theme === "dark" ? "浅色模式" : "深色模式"}
                    </button>

                    <div className="border-t border-[var(--color-border)] my-1" />

                    <button
                      onClick={handleLogout}
                      className="w-full flex items-center gap-2.5 px-3.5 py-2 text-xs text-red-500 hover:bg-red-500/10 cursor-pointer transition-colors"
                    >
                      <SignOut size={14} weight="regular" aria-hidden="true" />
                      退出登录
                    </button>
                  </div>
                )}
              </div>
            ) : (
              <button
                onClick={() => openLoginModal()}
                className="px-4 py-1.5 rounded-full text-sm font-semibold bg-brand text-white
                  hover:bg-[#0077ed] hover:scale-[1.02] active:scale-[0.98]
                  transition-all duration-300 cursor-pointer"
              >
                登录
              </button>
            )}
          </div>
        </div>
      </nav>

      {/* 用户设置弹窗 */}
      <ChangePasswordDialog
        open={passwordDialogOpen}
        onClose={() => setPasswordDialogOpen(false)}
        currentEmail={user?.email ?? ""}
      />
      <ChangeEmailDialog
        open={emailDialogOpen}
        onClose={() => setEmailDialogOpen(false)}
        currentEmail={user?.email ?? ""}
        onSuccess={(newEmail) => {
          void newEmail;
        }}
      />
      <ChangeUsernameDialog
        open={usernameDialogOpen}
        onClose={() => setUsernameDialogOpen(false)}
        currentUsername={user?.username ?? ""}
      />
      <UsageDialog
        open={usageDialogOpen}
        onClose={() => setUsageDialogOpen(false)}
      />
    </>
  );
}
