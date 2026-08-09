/**
 * LoginModal — 全局登录/注册弹窗。
 *
 * 从 LandingNav 内部抽出，挂载到 App 顶层，替代独立的 /login 页面。
 * 任意位置通过 `openLoginModal()` 触发（dispatch `open-login-modal` 事件）。
 *
 * 触发方式：
 *   openLoginModal()                          // 默认登录 tab
 *   openLoginModal({ tab: "register" })       // 注册 tab
 *   openLoginModal({ tab: "login", email })   // 预填邮箱（忘记密码返回）
 */

import { useState, useEffect, type FormEvent } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { useAuth } from "../context/AuthContext";
import { MessagesSquare, Mail, Lock, User, Hash } from "lucide-react";
import { overlayVariants, panelVariants } from "./useModalMotion";

// ── Apple 风格输入框 ──

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
        className="w-full pl-9 pr-3 py-2.5 rounded-list bg-[#F2F2F7] text-sm text-[var(--color-text)]
          placeholder:text-[var(--color-text-muted)] outline-none border border-transparent
          focus:bg-white focus:border-brand/40 focus:ring-4 focus:ring-brand/15
          transition-all duration-200"
      />
    </div>
  );
}

interface LoginModalProps {
  onClose: () => void;
  /** 初始 tab：登录/注册 */
  initialTab?: "login" | "register";
  /** 初始邮箱（如忘记密码流程返回后预填） */
  initialEmail?: string;
}

export function LoginModal({
  onClose,
  initialTab = "login",
  initialEmail = "",
}: LoginModalProps) {
  const { login, register, sendCode } = useAuth();

  const [tab, setTab] = useState<"login" | "register">(initialTab);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [loading, setLoading] = useState(false);

  // 登录字段
  const [email, setEmail] = useState(initialEmail);
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
    <motion.div
      className="fixed inset-0 z-50 flex items-center justify-center"
      variants={overlayVariants}
      initial="hidden"
      animate="visible"
      exit="exit"
    >
      {/* 遮罩 */}
      <div className="absolute inset-0 bg-black/30 backdrop-blur-sm" onClick={onClose} />

      {/* 卡片（毛玻璃）— 统一弹簧入场（useModalMotion） */}
      <motion.div
        className="relative w-full max-w-sm mx-4 glass-card shadow-2xl shadow-black/10"
        variants={panelVariants}
        initial="hidden"
        animate="visible"
        exit="exit"
        style={{ transformOrigin: "center" }}
      >
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
          <div className="mx-auto w-14 h-14 rounded-input bg-brand/10 flex items-center justify-center mb-4">
            <MessagesSquare size={26} fill="currentColor" className="text-brand" />
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
          <div className="mx-6 mb-3 p-2.5 rounded-list bg-danger/10 border border-danger/20 text-danger text-xs">
            {error}
          </div>
        )}
        {success && (
          <div className="mx-6 mb-3 p-2.5 rounded-list bg-success/10 border border-success/20 text-success text-xs">
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
                icon={Mail}
              />
              <AppleInput
                type="password"
                value={password}
                onChange={setPassword}
                placeholder="密码"
                icon={Lock}
              />
              <button
                type="submit"
                disabled={loading}
                className="w-full py-2.5 rounded-full bg-brand text-white text-sm font-semibold
                  hover:bg-brand-hover hover:scale-[1.02] active:scale-[0.98]
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
              <AppleInput type="email" value={regEmail} onChange={setRegEmail} placeholder="邮箱" icon={Mail} />
              <AppleInput type="password" value={regPassword} onChange={setRegPassword} placeholder="密码（至少8位）" icon={Lock} />
              <AppleInput type="password" value={regConfirm} onChange={setRegConfirm} placeholder="确认密码" icon={Lock} />
              <div className="flex gap-2">
                <div className="flex-1">
                  <AppleInput value={regCode} onChange={setRegCode} placeholder="6位验证码" icon={Hash} maxLength={6} />
                </div>
                <button
                  type="button"
                  disabled={sendCodeLoading || cooldown > 0}
                  onClick={handleSendCode}
                  className="px-4 py-2.5 rounded-list bg-[var(--color-bg-secondary)] text-xs font-medium text-[var(--color-text-secondary)]
                    hover:bg-[var(--color-bg-secondary)] transition-colors cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed shrink-0"
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
                  hover:bg-brand-hover hover:scale-[1.02] active:scale-[0.98]
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
      </motion.div>
    </motion.div>
  );
}

// ── 全局触发与挂载 ──

/** 会话过期等整页刷新场景，回首页后据此自动打开登录弹窗 */
const LOGIN_MODAL_FLAG = "login-modal";

export interface OpenLoginModalOptions {
  tab?: "login" | "register";
  email?: string;
}

/** 任意位置打开登录弹窗 */
export function openLoginModal(opts?: OpenLoginModalOptions) {
  window.dispatchEvent(new CustomEvent("open-login-modal", { detail: opts }));
}

/**
 * 全局登录弹窗宿主：挂载到 App 顶层，监听 `open-login-modal` 事件。
 * 兼容旧调用（`new Event("open-login-modal")` 无 detail）。
 */
export function LoginModalHost() {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");

  // 整页刷新场景：clearSessionAndRedirect 写入的标志，回首页后自动弹登录
  useEffect(() => {
    if (sessionStorage.getItem(LOGIN_MODAL_FLAG) === "1") {
      sessionStorage.removeItem(LOGIN_MODAL_FLAG);
      setOpen(true);
    }
  }, []);

  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail as OpenLoginModalOptions | undefined;
      if (detail?.tab) setTab(detail.tab);
      if (typeof detail?.email === "string") setEmail(detail.email);
      setOpen(true);
    };
    window.addEventListener("open-login-modal", handler);
    return () => window.removeEventListener("open-login-modal", handler);
  }, []);

  return (
    <AnimatePresence>
      {open && (
        <LoginModal
          initialTab={tab}
          initialEmail={email}
          onClose={() => setOpen(false)}
        />
      )}
    </AnimatePresence>
  );
}

export default LoginModal;
