import { useState, useRef, useEffect, useCallback } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import {
  ChatCircleDots,
  FileText,
  ChatCircle,
  Books,
  Plus,
  Trash,
  PencilSimple,
  CaretLeft,
  Gear,
  SignOut,
  Key,
  EnvelopeSimple,
  User,
  CaretDown,
  Spinner,
  Gauge,
  Sun,
  Sparkle,
  Microphone,
  UserMinus,
  PaperPlaneTilt,
} from "@phosphor-icons/react";
import { useAuth } from "../context/AuthContext";
import { deleteAccount } from "../api/auth";
import { useToast } from "./Toast";
import { useTheme } from "../context/ThemeContext";
import { useAppChat, dispatchSelectConversation, dispatchCreateConversation, dispatchDeleteConversation, dispatchRenameConversation } from "../context/AppChatContext";
import ChangePasswordDialog from "./ChangePasswordDialog";
import ChangeEmailDialog from "./ChangeEmailDialog";
import ChangeUsernameDialog from "./ChangeUsernameDialog";
import UsageDialog from "./UsageDialog";
import ConfirmDialog from "./ConfirmDialog";
import type { QuotaResponse } from "../api/qa";

// ── 导航项配置 ──

interface NavItem {
  path: string;
  label: string;
  icon: typeof ChatCircleDots;
  /** 路由匹配模式：exact 或 prefix */
  match: "exact" | "prefix";
}

const NAV_ITEMS: NavItem[] = [
  { path: "/qa", label: "Agent", icon: ChatCircleDots, match: "exact" },
  { path: "/resumes", label: "简历", icon: FileText, match: "prefix" },
  { path: "/assets", label: "知识资产", icon: Books, match: "exact" },
  { path: "/capabilities", label: "AI 能力", icon: Sparkle, match: "exact" },
  { path: "/interviews", label: "面试复盘", icon: Microphone, match: "exact" },
  { path: "/applications", label: "投递看板", icon: PaperPlaneTilt, match: "exact" },
  { path: "/feedback", label: "用户反馈", icon: ChatCircle, match: "exact" },
];

interface SidebarProps {
  collapsed: boolean;
  onToggleCollapse: () => void;
}

export default function Sidebar({ collapsed, onToggleCollapse }: SidebarProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const { user, logout } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const { conversations, activeConversationId, conversationLoading } = useAppChat();
  const toast = useToast();

  // 用户菜单
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [passwordDialogOpen, setPasswordDialogOpen] = useState(false);
  const [emailDialogOpen, setEmailDialogOpen] = useState(false);
  const [usernameDialogOpen, setUsernameDialogOpen] = useState(false);
  const [usageDialogOpen, setUsageDialogOpen] = useState(false);
  const [deleteAccountOpen, setDeleteAccountOpen] = useState(false);
  const [deletingAccount, setDeletingAccount] = useState(false);
  const [quota, setQuota] = useState<QuotaResponse | null>(null);
  const userMenuRef = useRef<HTMLDivElement>(null);

  // Token 用量：加载 + 监听 quota:refresh 事件 + 30s 轮询
  useEffect(() => {
    const fetchQuota = () => {
      import("../api/qa")
        .then(({ getQuota }) => getQuota())
        .then((data) => setQuota(data))
        .catch(() => {});
    };
    fetchQuota();
    const handler = () => fetchQuota();
    window.addEventListener("quota:refresh", handler);
    const interval = setInterval(fetchQuota, 30000);
    return () => {
      window.removeEventListener("quota:refresh", handler);
      clearInterval(interval);
    };
  }, []);

  // 对话操作
  const [renameTargetId, setRenameTargetId] = useState<number | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [deleteTargetId, setDeleteTargetId] = useState<number | null>(null);

  // 点击外部关闭用户菜单
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (userMenuRef.current && !userMenuRef.current.contains(event.target as Node)) {
        setUserMenuOpen(false);
      }
    };
    if (userMenuOpen) {
      document.addEventListener("mousedown", handleClickOutside);
      return () => document.removeEventListener("mousedown", handleClickOutside);
    }
  }, [userMenuOpen]);

  const isActive = useCallback(
    (item: NavItem) => {
      if (item.match === "exact") return location.pathname === item.path;
      // prefix: 匹配 /resumes 和 /resumes/:id/edit
      return location.pathname.startsWith(item.path);
    },
    [location.pathname],
  );

  const handleLogout = async () => {
    await logout();
    navigate("/");
  };

  /** C3：注销账号（级联清理全部数据，不可撤销） */
  const handleDeleteAccount = async () => {
    setDeletingAccount(true);
    try {
      await deleteAccount();
      toast.success("账户已注销，感谢使用");
    } catch {
      toast.error("注销失败，请重试");
      setDeletingAccount(false);
      setDeleteAccountOpen(false);
      return;
    }
    setDeletingAccount(false);
    setDeleteAccountOpen(false);
    // 清理本地会话并回首页
    await logout();
    navigate("/");
  };

  const handleRenameSubmit = () => {
    if (renameTargetId && renameValue.trim()) {
      dispatchRenameConversation(renameTargetId, renameValue.trim());
      setRenameTargetId(null);
      setRenameValue("");
    }
  };

  if (!user) return null;

  return (
    <>
      <aside
        className={`shrink-0 border-r border-[var(--color-border)] bg-white/80 backdrop-blur-xl flex flex-col h-full transition-all duration-300 ${
          collapsed ? "w-14" : "w-60"
        }`}
      >
        {/* ── Logo 区 ── */}
        <div className="shrink-0 flex items-center justify-between px-3 py-3 border-b border-[var(--color-border)]">
          {!collapsed && (
            <button
              onClick={() => navigate("/")}
              className="flex items-center gap-2 no-underline"
            >
              <svg viewBox="0 0 64 64" className="w-6 h-6 shrink-0">
                <polygon points="32,6 54,18 32,30 10,18" fill="#F5C547" />
                <polygon points="10,18 32,30 32,54 10,42" fill="#38D4D4" />
                <polygon points="32,30 54,18 54,42 32,54" fill="#8B5CF6" />
              </svg>
              <span className="text-xs font-semibold text-[var(--color-text)]">
                轻舟简历
              </span>
            </button>
          )}
          {collapsed && (
            <button
              onClick={() => navigate("/")}
              className="flex items-center justify-center w-full"
            >
              <svg viewBox="0 0 64 64" className="w-6 h-6 shrink-0">
                <polygon points="32,6 54,18 32,30 10,18" fill="#F5C547" />
                <polygon points="10,18 32,30 32,54 10,42" fill="#38D4D4" />
                <polygon points="32,30 54,18 54,42 32,54" fill="#8B5CF6" />
              </svg>
            </button>
          )}
          <button
            onClick={onToggleCollapse}
            className="p-1 rounded-md text-[var(--color-text-muted)] hover:text-brand hover:bg-brand/10 active:scale-90 transition-all cursor-pointer"
            aria-label={collapsed ? "展开侧边栏" : "折叠侧边栏"}
            title={collapsed ? "展开侧边栏" : "折叠侧边栏"}
          >
            <CaretLeft
              size={14}
              weight="bold"
              className={`transition-transform duration-300 ${collapsed ? "rotate-180" : ""}`}
              aria-hidden="true"
            />
          </button>
        </div>

        {/* ── 导航菜单 ── */}
        <nav className="shrink-0 px-2 py-2 space-y-0.5">
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            const active = isActive(item);
            return (
              <button
                key={item.path}
                onClick={() => navigate(item.path)}
                title={collapsed ? item.label : undefined}
                className={`w-full flex items-center gap-2.5 rounded-lg text-xs font-medium transition-all cursor-pointer
                  ${collapsed ? "justify-center px-1 py-2" : "px-3 py-2"}
                  ${active
                    ? "bg-brand/10 text-brand border border-brand/30"
                    : "text-[var(--color-text-secondary)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-secondary)] border border-transparent"
                  }`}
                aria-label={item.label}
                aria-current={active ? "page" : undefined}
              >
                <Icon
                  size={16}
                  weight={active ? "fill" : "regular"}
                  className="shrink-0"
                  aria-hidden="true"
                />
                {!collapsed && <span className="truncate">{item.label}</span>}
              </button>
            );
          })}
        </nav>

        {/* ── 对话历史区 ── */}
        {!collapsed && (
          <div className="flex-1 overflow-y-auto min-h-0 border-t border-[var(--color-border)]">
            <div className="flex items-center justify-between px-3 py-2">
              <span className="text-[10px] font-medium text-[var(--color-text-muted)] uppercase tracking-wider">
                对话
              </span>
              <button
                onClick={() => dispatchCreateConversation()}
                className="p-1 rounded-md text-[var(--color-text-muted)] hover:text-brand hover:bg-brand/10 active:scale-90 transition-all cursor-pointer"
                aria-label="新建对话"
                title="新建对话"
              >
                <Plus size={12} weight="bold" aria-hidden="true" />
              </button>
            </div>

            <div className="px-1 pb-2">
              {conversationLoading ? (
                <div className="flex items-center justify-center py-4">
                  <Spinner size={14} className="animate-spin text-[var(--color-text-muted)]" aria-hidden="true" />
                </div>
              ) : conversations.length === 0 ? (
                <p className="px-3 py-2 text-[10px] text-[var(--color-text-muted)]">
                  暂无对话
                </p>
              ) : (
                <ul className="space-y-0.5">
                  {conversations.map((conv) => {
                    const active = conv.id === activeConversationId;
                    return (
                      <li key={conv.id} className="group relative">
                        {renameTargetId === conv.id ? (
                          /* 重命名输入框 */
                          <div className="px-2 py-1">
                            <input
                              autoFocus
                              value={renameValue}
                              onChange={(e) => setRenameValue(e.target.value)}
                              onBlur={handleRenameSubmit}
                              onKeyDown={(e) => {
                                if (e.key === "Enter") handleRenameSubmit();
                                if (e.key === "Escape") {
                                  setRenameTargetId(null);
                                  setRenameValue("");
                                }
                              }}
                              className="w-full px-2 py-1 rounded-md text-xs bg-[var(--color-bg-secondary)] border border-brand/40 text-[var(--color-text)] outline-none"
                            />
                          </div>
                        ) : (
                          <div
                            className={`flex items-center rounded-lg transition-all
                              ${active
                                ? "bg-brand/10 border border-brand/20"
                                : "border border-transparent hover:bg-[var(--color-bg-secondary)]"
                              }`}
                          >
                            <button
                              onClick={() => dispatchSelectConversation(conv.id)}
                              className="flex-1 flex items-center gap-2 min-w-0 px-2.5 py-1.5 text-left cursor-pointer"
                              title={conv.title}
                            >
                              <ChatCircleDots
                                size={12}
                                weight={active ? "fill" : "regular"}
                                className={`shrink-0 ${active ? "text-brand" : "text-[var(--color-text-muted)]"}`}
                                aria-hidden="true"
                              />
                              <span className={`flex-1 min-w-0 truncate text-[11px] ${
                                active ? "text-brand font-medium" : "text-[var(--color-text-secondary)]"
                              }`}>
                                {conv.title}
                              </span>
                              <span className="shrink-0 text-[9px] text-[var(--color-text-muted)] tabular-nums">
                                {conv.message_count}
                              </span>
                            </button>
                            {/* hover 操作按钮 */}
                            <div className="shrink-0 flex items-center pr-1 opacity-0 group-hover:opacity-100 transition-opacity">
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setRenameTargetId(conv.id);
                                  setRenameValue(conv.title);
                                }}
                                className="p-1 rounded text-[var(--color-text-muted)] hover:text-brand hover:bg-brand/10 transition-all cursor-pointer"
                                aria-label="重命名"
                                title="重命名"
                              >
                                <PencilSimple size={10} weight="regular" aria-hidden="true" />
                              </button>
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setDeleteTargetId(conv.id);
                                }}
                                className="p-1 rounded text-[var(--color-text-muted)] hover:text-red-400 hover:bg-red-500/10 transition-all cursor-pointer"
                                aria-label="删除"
                                title="删除"
                              >
                                <Trash size={10} weight="regular" aria-hidden="true" />
                              </button>
                            </div>
                          </div>
                        )}
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          </div>
        )}

        {/* 折叠模式下占位 */}
        {collapsed && <div className="flex-1" />}

        {/* ── 底部用户信息区 ── */}
        <div className="shrink-0 border-t border-[var(--color-border)] p-2" ref={userMenuRef}>
          <div className="relative">
            <button
              onClick={() => setUserMenuOpen(!userMenuOpen)}
              className={`w-full flex items-center gap-2 rounded-lg p-1.5 transition-all cursor-pointer hover:bg-[var(--color-bg-secondary)]
                ${collapsed ? "justify-center" : ""}`}
              aria-label="用户菜单"
              aria-expanded={userMenuOpen}
            >
              {/* 头像 */}
              <div className="w-7 h-7 shrink-0 rounded-full bg-brand flex items-center justify-center text-white text-xs font-medium">
                {user.username.charAt(0).toUpperCase()}
              </div>
              {!collapsed && (
                <>
                  <div className="flex-1 min-w-0 text-left">
                    <p className="text-xs font-medium text-[var(--color-text)] truncate">
                      {user.username}
                    </p>
                    <p className="text-[9px] text-[var(--color-text-muted)] truncate">
                      {user.email}
                    </p>
                  </div>
                  <motion.div animate={{ rotate: userMenuOpen ? 180 : 0 }} transition={{ duration: 0.2 }}>
                    <CaretDown size={10} className="text-[var(--color-text-muted)]" aria-hidden="true" />
                  </motion.div>
                </>
              )}
            </button>

            {/* 下拉菜单 */}
            <AnimatePresence>
              {userMenuOpen && (
                <motion.div
                  initial={{ opacity: 0, y: 5, scale: 0.95 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, y: 5, scale: 0.95 }}
                  transition={{ duration: 0.15 }}
                  className={`absolute z-50 w-48 rounded-2xl border border-[var(--color-border)] bg-white/90 backdrop-blur-xl shadow-2xl py-1
                    ${collapsed ? "left-full ml-2 bottom-0" : "bottom-full mb-2 left-0"}`}
                >
                  {/* Token 用量概览 */}
                  {quota?.enabled && (
                    <div className="px-3 py-2.5 border-b border-[var(--color-border)]">
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
                      className="w-full flex items-center gap-2.5 px-3 py-1.5 text-xs text-[var(--color-text-secondary)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-secondary)] transition-colors cursor-pointer"
                    >
                      <Gear size={14} weight="regular" aria-hidden="true" />
                      管理后台
                    </button>
                  )}

                  <div className="border-t border-[var(--color-border)] my-1" />

                  {/* 修改密码 */}
                  <button
                    onClick={() => { setPasswordDialogOpen(true); setUserMenuOpen(false); }}
                    className="w-full flex items-center gap-2.5 px-3 py-1.5 text-xs text-[var(--color-text-secondary)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-secondary)] transition-colors cursor-pointer"
                  >
                    <Key size={14} weight="regular" aria-hidden="true" />
                    修改密码
                  </button>

                  {/* 重新绑定邮箱 */}
                  <button
                    onClick={() => { setEmailDialogOpen(true); setUserMenuOpen(false); }}
                    className="w-full flex items-center gap-2.5 px-3 py-1.5 text-xs text-[var(--color-text-secondary)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-secondary)] transition-colors cursor-pointer"
                  >
                    <EnvelopeSimple size={14} weight="regular" aria-hidden="true" />
                    重新绑定邮箱
                  </button>

                  {/* 修改用户名 */}
                  <button
                    onClick={() => { setUsernameDialogOpen(true); setUserMenuOpen(false); }}
                    className="w-full flex items-center gap-2.5 px-3 py-1.5 text-xs text-[var(--color-text-secondary)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-secondary)] transition-colors cursor-pointer"
                  >
                    <User size={14} weight="regular" aria-hidden="true" />
                    修改用户名
                  </button>

                  {/* 用量统计 */}
                  <button
                    onClick={() => { setUsageDialogOpen(true); setUserMenuOpen(false); }}
                    className="w-full flex items-center gap-2.5 px-3 py-1.5 text-xs text-[var(--color-text-secondary)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-secondary)] transition-colors cursor-pointer"
                  >
                    <Gauge size={14} weight="regular" aria-hidden="true" />
                    用量统计
                  </button>

                  {/* 主题切换 */}
                  <button
                    onClick={toggleTheme}
                    className="w-full flex items-center gap-2.5 px-3 py-1.5 text-xs text-[var(--color-text-secondary)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-secondary)] transition-colors cursor-pointer"
                  >
                    <Sun size={14} weight={theme === "dark" ? "fill" : "regular"} aria-hidden="true" />
                    {theme === "dark" ? "浅色模式" : "深色模式"}
                  </button>

                  <div className="border-t border-[var(--color-border)] my-1" />

                  {/* 注销账号（C3） */}
                  <button
                    onClick={() => setDeleteAccountOpen(true)}
                    className="w-full flex items-center gap-2.5 px-3 py-1.5 text-xs text-red-400/80 hover:bg-red-500/10 transition-colors cursor-pointer"
                  >
                    <UserMinus size={14} weight="regular" aria-hidden="true" />
                    注销账号
                  </button>

                  {/* 退出登录 */}
                  <button
                    onClick={handleLogout}
                    className="w-full flex items-center gap-2.5 px-3 py-1.5 text-xs text-red-400 hover:bg-red-500/10 transition-colors cursor-pointer"
                  >
                    <SignOut size={14} weight="regular" aria-hidden="true" />
                    退出登录
                  </button>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </div>
      </aside>

      {/* ── Dialogs ── */}
      <ChangePasswordDialog
        open={passwordDialogOpen}
        onClose={() => setPasswordDialogOpen(false)}
        currentEmail={user.email}
      />
      <ChangeEmailDialog
        open={emailDialogOpen}
        onClose={() => setEmailDialogOpen(false)}
        currentEmail={user.email}
        onSuccess={(newEmail) => {
          // AuthContext.updateUser 会在 dialog 内部调用
          void newEmail;
        }}
      />
      <ChangeUsernameDialog
        open={usernameDialogOpen}
        onClose={() => setUsernameDialogOpen(false)}
        currentUsername={user.username}
      />
      <UsageDialog
        open={usageDialogOpen}
        onClose={() => setUsageDialogOpen(false)}
      />

      {/* 删除对话确认 */}
      <ConfirmDialog
        open={deleteTargetId !== null}
        title="确认删除"
        description="确定删除这个对话吗？对话中的所有问答将一并删除，此操作不可撤销。"
        confirmText="删除"
        danger
        onConfirm={() => {
          if (deleteTargetId !== null) {
            dispatchDeleteConversation(deleteTargetId);
            setDeleteTargetId(null);
          }
        }}
        onCancel={() => setDeleteTargetId(null)}
      />

      {/* 注销账号确认（C3） */}
      <ConfirmDialog
        open={deleteAccountOpen}
        title="确认注销账号"
        description="注销后将永久删除你的全部简历、问答历史、知识资产、面试记录与投递跟踪，此操作不可撤销。确定继续吗？"
        confirmText="注销账号"
        danger
        loading={deletingAccount}
        onConfirm={() => void handleDeleteAccount()}
        onCancel={() => setDeleteAccountOpen(false)}
      />
    </>
  );
}
