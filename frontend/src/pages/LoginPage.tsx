import { useState, useEffect, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

function Spinner() {
  return (
    <svg
      className="animate-spin-slow h-5 w-5 text-white/80"
      xmlns="http://www.w3.org/2000/svg"
      fill="none"
      viewBox="0 0 24 24"
    >
      <circle
        className="opacity-25"
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="4"
      />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
      />
    </svg>
  );
}

function FeaturePill({
  label,
  color,
}: {
  label: string;
  color: "indigo" | "violet" | "sky";
}) {
  const colorMap = {
    indigo: "bg-indigo-500/15 border-indigo-500/20 text-indigo-300",
    violet: "bg-violet-500/15 border-violet-500/20 text-violet-300",
    sky: "bg-sky-500/15 border-sky-500/20 text-sky-300",
  };
  return (
    <span
      className={`inline-block px-3 py-1 rounded-full border text-xs font-medium ${colorMap[color]}`}
    >
      {label}
    </span>
  );
}

function FormInput({
  id,
  label,
  type = "text",
  value,
  onChange,
  placeholder,
  required = true,
  error,
}: {
  id: string;
  label: string;
  type?: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  required?: boolean;
  error?: string;
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block text-sm font-medium text-slate-300">
        {label}
      </label>
      <input
        id={id}
        type={type}
        required={required}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className={`w-full px-4 py-3 rounded-xl text-sm text-slate-200
          bg-white/5 border transition-all duration-200
          placeholder:text-slate-500
          focus:outline-none focus:ring-2 focus:ring-indigo-500/40
          focus:border-indigo-500/50 focus:shadow-[0_0_15px_rgba(99,102,241,0.15)]
          ${error ? "border-red-500/60" : "border-white/10"}`}
      />
      {error && (
        <p className="text-xs text-red-400 animate-shake">{error}</p>
      )}
    </div>
  );
}

// ── 主组件 ──────────────────────────────────────────────

export default function LoginPage() {
  const { login, register } = useAuth();
  const navigate = useNavigate();

  const [tab, setTab] = useState<"login" | "register">("login");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [loading, setLoading] = useState(false);
  const [mounted, setMounted] = useState(false);

  // 登录字段
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  // 注册字段
  const [username, setUsername] = useState("");
  const [regEmail, setRegEmail] = useState("");
  const [regPassword, setRegPassword] = useState("");
  const [regConfirm, setRegConfirm] = useState("");

  // Tab 切换动画状态
  const [formVisible, setFormVisible] = useState(true);

  // 字段级错误
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    setMounted(true);
  }, []);

  const switchTab = (t: "login" | "register") => {
    if (t === tab) return;
    setFormVisible(false);
    setTimeout(() => {
      setTab(t);
      setError("");
      setSuccess("");
      setFieldErrors({});
      setFormVisible(true);
    }, 150);
  };

  const validateLogin = (): boolean => {
    const errs: Record<string, string> = {};
    if (!email.trim()) errs.email = "请输入邮箱";
    if (!password) errs.password = "请输入密码";
    setFieldErrors(errs);
    return Object.keys(errs).length === 0;
  };

  const validateRegister = (): boolean => {
    const errs: Record<string, string> = {};
    if (!username.trim() || username.trim().length < 2)
      errs.username = "用户名至少2个字符";
    if (!regEmail.trim()) errs.regEmail = "请输入邮箱";
    if (!regPassword || regPassword.length < 8)
      errs.regPassword = "密码至少8位，需包含字母和数字";
    if (regPassword !== regConfirm) errs.regConfirm = "两次密码不一致";
    setFieldErrors(errs);
    return Object.keys(errs).length === 0;
  };

  // ── 登录 ──
  const handleLogin = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    if (!validateLogin()) return;

    setLoading(true);
    try {
      await login(email, password);
      navigate("/");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "登录失败");
    } finally {
      setLoading(false);
    }
  };

  // ── 注册 ──
  const handleRegister = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setSuccess("");
    if (!validateRegister()) return;

    setLoading(true);
    try {
      await register(username, regEmail, regPassword, regConfirm);
      setSuccess("注册成功，请登录");
      setTimeout(() => switchTab("login"), 600);
      setEmail(regEmail);
      setPassword("");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "注册失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex flex-col md:flex-row">
      {/* ═══ 左面板：品牌展示 ═══ */}
      <div
        className="relative flex-1 flex flex-col justify-center items-center
          px-8 py-12 md:py-0 overflow-hidden
          bg-linear-to-br from-[#0f0a2e] via-[#1a0a2e] to-[#2d1b69]"
      >
        {/* 光斑装饰 */}
        <div
          className="absolute -top-12 -left-12 w-64 h-64 rounded-full
            bg-purple-500/20 blur-[60px] animate-float"
        />
        <div
          className="absolute -bottom-8 -right-8 w-56 h-56 rounded-full
            bg-indigo-400/15 blur-[60px] animate-float-reverse"
        />

        {/* 品牌内容 */}
        <div
          className={`relative z-10 text-center transition-all duration-500
            ${mounted ? "opacity-100 translate-y-0" : "opacity-0 translate-y-4"}`}
        >
          {/* Logo */}
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl mb-6
            bg-linear-to-br from-indigo-500 to-purple-600 shadow-lg shadow-indigo-500/25">
            <span className="text-white text-2xl font-bold tracking-tight">R</span>
          </div>

          {/* 标题 */}
          <h1 className="text-3xl md:text-4xl font-bold mb-3
            bg-linear-to-r from-indigo-200 to-purple-300 bg-clip-text text-transparent">
            AI Resume Analyzer
          </h1>
          <p className="text-slate-400 text-sm mb-8">
            智能简历分析系统
          </p>

          {/* 特性标签 */}
          <div className="flex flex-wrap justify-center gap-2.5">
            <FeaturePill label="RAG 问答" color="indigo" />
            <FeaturePill label="混合检索" color="violet" />
            <FeaturePill label="SSE 流式" color="sky" />
          </div>
        </div>
      </div>

      {/* ═══ 右面板：登录表单 ═══ */}
      <div className="flex-1 flex items-center justify-center bg-[#0f172a] px-6 py-12 md:py-0">
        <div className="w-full max-w-md">
          {/* 玻璃卡片 */}
          <div className="bg-white/5 backdrop-blur-xl border border-white/10 rounded-2xl p-8">
            {/* 欢迎文字 */}
            <div className="mb-6">
              <h2 className="text-xl font-semibold text-slate-100">
                {tab === "login" ? "欢迎回来" : "创建账号"}
              </h2>
              <p className="text-sm text-slate-500 mt-1">
                {tab === "login" ? "登录以继续使用" : "注册以开始分析简历"}
              </p>
            </div>

            {/* Tab 切换 */}
            <div className="flex bg-white/4 rounded-xl p-1 mb-6">
              {(["login", "register"] as const).map((t) => (
                <button
                  key={t}
                  onClick={() => switchTab(t)}
                  className={`flex-1 py-2.5 text-sm font-medium rounded-lg transition-all duration-200 cursor-pointer
                    ${
                      tab === t
                        ? "bg-indigo-500/20 text-indigo-300 shadow-sm"
                        : "text-slate-500 hover:text-slate-300"
                    }`}
                >
                  {t === "login" ? "登录" : "注册"}
                </button>
              ))}
            </div>

            {/* 全局错误提示 */}
            {error && (
              <div className="mb-4 p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm animate-shake">
                {error}
              </div>
            )}
            {/* 全局成功提示 */}
            {success && (
              <div className="mb-4 p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-sm">
                {success}
              </div>
            )}

            {/* 表单区域（带过渡动画） */}
            <div
              className={`transition-all duration-150
                ${formVisible ? "opacity-100 translate-y-0" : "opacity-0 -translate-y-2"}`}
            >
              {tab === "login" ? (
                <form onSubmit={handleLogin} className="space-y-4">
                  <FormInput
                    id="login-email"
                    label="邮箱"
                    type="email"
                    value={email}
                    onChange={setEmail}
                    placeholder="your@email.com"
                    error={fieldErrors.email}
                  />
                  <FormInput
                    id="login-password"
                    label="密码"
                    type="password"
                    value={password}
                    onChange={setPassword}
                    placeholder="至少8位，需包含字母和数字"
                    error={fieldErrors.password}
                  />
                  <button
                    type="submit"
                    disabled={loading}
                    className="w-full py-3 mt-2 rounded-xl text-sm font-semibold text-white
                      bg-linear-to-r from-indigo-500 to-purple-600
                      hover:brightness-110 hover:shadow-lg hover:shadow-indigo-500/25
                      active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed
                      transition-all duration-200 cursor-pointer
                      flex items-center justify-center gap-2"
                  >
                    {loading ? <Spinner /> : "登 录"}
                  </button>
                </form>
              ) : (
                <form onSubmit={handleRegister} className="space-y-4">
                  <FormInput
                    id="reg-username"
                    label="用户名"
                    value={username}
                    onChange={setUsername}
                    placeholder="至少2个字符"
                    error={fieldErrors.username}
                  />
                  <FormInput
                    id="reg-email"
                    label="邮箱"
                    type="email"
                    value={regEmail}
                    onChange={setRegEmail}
                    placeholder="your@email.com"
                    error={fieldErrors.regEmail}
                  />
                  <FormInput
                    id="reg-password"
                    label="密码"
                    type="password"
                    value={regPassword}
                    onChange={setRegPassword}
                    placeholder="至少8位，需包含字母和数字"
                    error={fieldErrors.regPassword}
                  />
                  <FormInput
                    id="reg-confirm"
                    label="确认密码"
                    type="password"
                    value={regConfirm}
                    onChange={setRegConfirm}
                    placeholder="再输一遍"
                    error={fieldErrors.regConfirm}
                  />
                  <button
                    type="submit"
                    disabled={loading}
                    className="w-full py-3 mt-2 rounded-xl text-sm font-semibold text-white
                      bg-linear-to-r from-indigo-500 to-purple-600
                      hover:brightness-110 hover:shadow-lg hover:shadow-indigo-500/25
                      active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed
                      transition-all duration-200 cursor-pointer
                      flex items-center justify-center gap-2"
                  >
                    {loading ? <Spinner /> : "注 册"}
                  </button>
                </form>
              )}
            </div>
          </div>

          {/* 底部提示 */}
          <p className="text-center text-xs text-slate-600 mt-6">
            AI 驱动的简历分析 · RAG + 混合检索 + 流式生成
          </p>
        </div>
      </div>
    </div>
  );
}
