/**
 * LandingNav — 首页/内容页共享顶部导航（Apple 风格）。
 *
 * 浅色毛玻璃顶栏 + 品牌蓝胶囊按钮 + 毛玻璃登录弹窗。
 */

import { useState, useEffect, useRef, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { Sparkle, CaretDown, EnvelopeSimple, LockSimple, User, Hash, Shield, Key, Gauge, SignOut, Sun } from "@phosphor-icons/react";
import { useTheme } from "../context/ThemeContext";
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
  { key: "templates", label: "简历模板", route: "/templates" },
  { key: "examples", label: "简历范文", route: "/examples" },
  { key: "tips", label: "求职攻略", route: "/tips" },
  { key: "campus", label: "校招信息", route: "/campus" },
  { key: "social", label: "社招信息", route: "/social" },
  { key: "feedback", label: "用户反馈", route: "/feedback" },
  { key: "updates", label: "产品更新", route: "/product-updates" },
];

// ── 输入框（Apple 风格） ──

function AppleInput({
  type = "text",
  value,
  onChange,
  placeholder,
  icon: Icon,
  maxLength,
}: {
  type?: string;
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
  maxLength?: number;
}) {
  return (
    <div className="relative">
      <Icon
        size={14}
        className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[var(--color-text-muted)]"
      />
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        maxLength={maxLength}
        className="w-full pl-9 pr-3 py-2.5 rounded-xl bg-[#F2F2F7] text-sm text-[var(--color-text)]
          placeholder:text-[var(--color-text-muted)] outline-none border border-transparent
          focus:bg-white focus:border-brand/40 focus:ring-4 focus:ring-brand/15
          transition-all duration-200"
      />
    </div>
  );
}

// ── 登录/注册弹窗 ──

function LoginModal({ onClose }: { onClose: () => void }) {
  const { login, register, sendCode } = useAuth();

  const [tab, setTab] = useState<"login" | "register">("login");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [loading, setLoading] = useState(false);

  // 登录字段
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  // 注册字段
  const [regUsername, setRegUsername] = useState("");
  const [regEmail, setRegEmail] = useState("");
  const [regPassword, setRegPassword] = useState("");
  const [regConfirm, setRegConfirm] = useState("");
  const [regCode, setRegCode] = useState("");
  const [sendCodeLoading, setSendCodeLoading] = useState(false);
  const [cooldown, setCooldown] = useState(0);

  // ESC 关闭
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [onClose]);

  const handleSendCode = async () => {
    if (cooldown > 0 || sendCodeLoading) return;
    if (!regEmail.trim()) {
      setError("请输入邮箱");
      return;
    }
    setSendCodeLoading(true);
    setError("");
    try {
      await sendCode(regEmail);
      setSuccess("验证码已发送");
      setCooldown(60);
      const timer = setInterval(() => {
        setCooldown((prev) => {
          if (prev <= 1) {
            clearInterval(timer);
            return 0;
          }
          return prev - 1;
        });
      }, 1000);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "发送验证码失败");
    } finally {
      setSendCodeLoading(false);
    }
  };

  const handleLogin = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    if (!email.trim() || !password) {
      setError("请填写邮箱和密码");
      return;
    }
    setLoading(true);
    try {
      await login(email, password);
      onClose();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "登录失败");
    } finally {
      setLoading(false);
    }
  };

  const handleRegister = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setSuccess("");
    if (!regUsername.trim() || regUsername.trim().length < 2) {
      setError("用户名至少2个字符");
      return;
    }
    if (!regEmail.trim()) {
      setError("请输入邮箱");
      return;
    }
    if (!regPassword || regPassword.length < 8) {
      setError("密码至少8位，需包含字母和数字");
      return;
    }
    if (regPassword !== regConfirm) {
      setError("两次密码不一致");
      return;
    }
    if (!regCode || regCode.length !== 6) {
      setError("请输入6位验证码");
      return;
    }
    setLoading(true);
    try {
      await register(regUsername, regEmail, regPassword, regConfirm, regCode);
      await login(regEmail, regPassword);
      onClose();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "注册失败");
    } finally {
      setLoading(false);
    }
  };

  const switchTab = (t: "login" | "register") => {
    setTab(t);
    setError("");
    setSuccess("");
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* 遮罩 */}
      <div className="absolute inset-0 bg-black/30 backdrop-blur-sm" onClick={onClose} />

      {/* 卡片（毛玻璃） */}
      <div className="relative w-full max-w-sm mx-4 glass-card shadow-2xl shadow-black/10 animate-fade-in-up">
        {/* 关闭按钮 */}
        <button
          onClick={onClose}
          className="absolute top-3 right-3 p-2 rounded-full text-[var(--color-text-muted)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-secondary)] transition-all cursor-pointer z-10"
          aria-label="关闭"
        >
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
            <path d="M3 3l10 10M13 3L3 13" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
        </button>

        {/* 标题 */}
        <div className="px-6 pt-7 pb-4 text-center">
          <div className="mx-auto w-14 h-14 rounded-2xl bg-brand/10 flex items-center justify-center mb-4">
            <Sparkle size={26} weight="fill" className="text-brand" />
          </div>
          <h2 className="text-xl font-bold text-[var(--color-text)] display-tight">
            {tab === "login" ? "欢迎回来" : "创建账号"}
          </h2>
          <p className="text-xs text-[var(--color-text-muted)] mt-1.5">
            {tab === "login" ? "登录以使用 AI 简历助手" : "注册以开始分析简历"}
          </p>
        </div>

        {/* Tab 切换 */}
        <div className="flex mx-6 mb-4 p-1 rounded-full bg-[var(--color-bg-secondary)]">
          {(["login", "register"] as const).map((t) => (
            <button
              key={t}
              onClick={() => switchTab(t)}
              className={`flex-1 py-2 text-xs font-medium rounded-full transition-all cursor-pointer
                ${tab === t
                  ? "bg-white text-[var(--color-text)] shadow-sm"
                  : "text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)]"
                }`}
            >
              {t === "login" ? "登录" : "注册"}
            </button>
          ))}
        </div>

        {/* 错误/成功提示 */}
        {error && (
          <div className="mx-6 mb-3 p-2.5 rounded-xl bg-red-500/10 border border-red-500/20 text-red-500 text-xs">
            {error}
          </div>
        )}
        {success && (
          <div className="mx-6 mb-3 p-2.5 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-500 text-xs">
            {success}
          </div>
        )}

        {/* 表单 */}
        <div className="px-6 pb-7">
          {tab === "login" ? (
            <form onSubmit={handleLogin} className="space-y-3">
              <AppleInput
                type="email"
                value={email}
                onChange={setEmail}
                placeholder="邮箱"
                icon={EnvelopeSimple}
              />
              <AppleInput
                type="password"
                value={password}
                onChange={setPassword}
                placeholder="密码"
                icon={LockSimple}
              />
              <button
                type="submit"
                disabled={loading}
                className="w-full py-2.5 rounded-full bg-brand text-white text-sm font-semibold
                  hover:bg-[#0077ed] hover:scale-[1.02] active:scale-[0.98]
                  transition-all duration-300 cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed"
              >
                {loading ? (
                  <span className="inline-block w-4 h-4 border-2 border-white/70 border-t-transparent rounded-full animate-spin" />
                ) : (
                  "登录"
                )}
              </button>
              <p className="text-center text-xs text-[var(--color-text-muted)] pt-1">
                没有账号？{" "}
                <button
                  type="button"
                  onClick={() => switchTab("register")}
                  className="text-brand hover:underline cursor-pointer"
                >
                  立即注册
                </button>
              </p>
            </form>
          ) : (
            <form onSubmit={handleRegister} className="space-y-3">
              <AppleInput value={regUsername} onChange={setRegUsername} placeholder="用户名（至少2个字符）" icon={User} />
              <AppleInput type="email" value={regEmail} onChange={setRegEmail} placeholder="邮箱" icon={EnvelopeSimple} />
              <AppleInput type="password" value={regPassword} onChange={setRegPassword} placeholder="密码（至少8位）" icon={LockSimple} />
              <AppleInput type="password" value={regConfirm} onChange={setRegConfirm} placeholder="确认密码" icon={LockSimple} />
              <div className="flex gap-2">
                <div className="flex-1">
                  <AppleInput value={regCode} onChange={setRegCode} placeholder="6位验证码" icon={Hash} maxLength={6} />
                </div>
                <button
                  type="button"
                  disabled={sendCodeLoading || cooldown > 0}
                  onClick={handleSendCode}
                  className="px-4 py-2.5 rounded-xl bg-[var(--color-bg-secondary)] text-xs font-medium text-[var(--color-text-secondary)]
                    hover:bg-[#E5E5EA] transition-colors cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed shrink-0"
                >
                  {sendCodeLoading ? (
                    <span className="inline-block w-3.5 h-3.5 border-2 border-current border-t-transparent rounded-full animate-spin" />
                  ) : cooldown > 0 ? (
                    `${cooldown}s`
                  ) : (
                    "发送"
                  )}
                </button>
              </div>
              <button
                type="submit"
                disabled={loading}
                className="w-full py-2.5 rounded-full bg-brand text-white text-sm font-semibold
                  hover:bg-[#0077ed] hover:scale-[1.02] active:scale-[0.98]
                  transition-all duration-300 cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed"
              >
                {loading ? (
                  <span className="inline-block w-4 h-4 border-2 border-white/70 border-t-transparent rounded-full animate-spin" />
                ) : (
                  "注册"
                )}
              </button>
              <p className="text-center text-xs text-[var(--color-text-muted)] pt-1">
                已有账号？{" "}
                <button
                  type="button"
                  onClick={() => switchTab("login")}
                  className="text-brand hover:underline cursor-pointer"
                >
                  返回登录
                </button>
              </p>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}

// ── 顶部导航 ──

interface LandingNavProps {
  /** 当前高亮的导航 key（默认无高亮） */
  activeKey?: string;
}

export default function LandingNav({ activeKey }: LandingNavProps) {
  const { user, logout } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const navigate = useNavigate();

  const [loginModalOpen, setLoginModalOpen] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [passwordDialogOpen, setPasswordDialogOpen] = useState(false);
  const [emailDialogOpen, setEmailDialogOpen] = useState(false);
  const [usernameDialogOpen, setUsernameDialogOpen] = useState(false);
  const [usageDialogOpen, setUsageDialogOpen] = useState(false);
  const [quota, setQuota] = useState<QuotaResponse | null>(null);
  const userMenuRef = useRef<HTMLDivElement>(null);

  // 支持外部触发登录弹窗（如首页 Hero 的 CTA）
  useEffect(() => {
    const handler = () => setLoginModalOpen(true);
    window.addEventListener("open-login-modal", handler);
    return () => window.removeEventListener("open-login-modal", handler);
  }, []);

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
      setLoginModalOpen(true);
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
                onClick={() => setLoginModalOpen(true)}
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

      {/* 登录弹窗 */}
      {loginModalOpen && <LoginModal onClose={() => setLoginModalOpen(false)} />}

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
