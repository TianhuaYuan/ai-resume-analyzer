import { useState, useEffect, type FormEvent } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { motion } from "framer-motion";
import { User, Mail, Lock, ArrowRight } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { SignInCard2 } from "../components/ui/sign-in-card-2";
import { cn } from "@/lib/utils";

function FieldError({ error }: { error?: string }) {
  if (!error) return null;
  return <p className="text-xs text-red-400 mt-1">{error}</p>;
}

function RegisterInput({
  id,
  label,
  type = "text",
  value,
  onChange,
  placeholder,
  required = true,
  error,
  icon: Icon,
}: {
  id: string;
  label: string;
  type?: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  required?: boolean;
  error?: string;
  icon: React.ComponentType<{ className?: string }>;
}) {
  return (
    <div className="space-y-1.5">
      <label
        htmlFor={id}
        className="block text-xs font-medium text-white/60"
      >
        {label}
      </label>
      <div className="relative flex items-center overflow-hidden rounded-lg">
        <Icon className="absolute left-3 w-4 h-4 text-white/40" />
        <input
          id={id}
          type={type}
          required={required}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className={cn(
            "w-full bg-white/5 border h-10 text-white placeholder:text-white/30 transition-all duration-300 pl-10 pr-3 focus:bg-white/10 rounded-lg outline-none",
            error ? "border-red-500/60" : "border-white/10 focus:border-white/20"
          )}
        />
      </div>
      <FieldError error={error} />
    </div>
  );
}

export default function LoginPage() {
  const { login, register } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [tab, setTab] = useState<"login" | "register">("login");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [loading, setLoading] = useState(false);

  // 登录字段
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  // 注册字段
  const [username, setUsername] = useState("");
  const [regEmail, setRegEmail] = useState("");
  const [regPassword, setRegPassword] = useState("");
  const [regConfirm, setRegConfirm] = useState("");

  // 字段级错误
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  // 从 forgot-password 返回时可能带 email
  useEffect(() => {
    const state = location.state as { email?: string } | null;
    if (state?.email) setEmail(state.email);
  }, [location.state]);

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
      setTimeout(() => {
        setTab("login");
        setEmail(regEmail);
        setPassword("");
      }, 600);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "注册失败");
    } finally {
      setLoading(false);
    }
  };

  // ═══ 登录视图：使用 SignInCard2 ═══
  if (tab === "login") {
    return (
      <>
        <SignInCard2
          email={email}
          password={password}
          onEmailChange={setEmail}
          onPasswordChange={setPassword}
          onSubmit={handleLogin}
          isLoading={loading}
          onForgotPassword={() => navigate("/forgot-password")}
          onSignUp={() => {
            setTab("register");
            setError("");
            setFieldErrors({});
          }}
        />
        {/* 全局错误/成功提示：浮动在卡片上方 */}
        {error && (
          <div className="fixed top-6 left-1/2 -translate-x-1/2 z-50 px-4 py-2 rounded-lg bg-red-500/20 border border-red-500/30 text-red-300 text-sm backdrop-blur-xl">
            {error}
          </div>
        )}
        {success && (
          <div className="fixed top-6 left-1/2 -translate-x-1/2 z-50 px-4 py-2 rounded-lg bg-emerald-500/20 border border-emerald-500/30 text-emerald-300 text-sm backdrop-blur-xl">
            {success}
          </div>
        )}
        {/* 字段错误提示 */}
        {(fieldErrors.email || fieldErrors.password) && (
          <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 px-4 py-2 rounded-lg bg-red-500/20 border border-red-500/30 text-red-300 text-xs backdrop-blur-xl">
            {fieldErrors.email && <p>{fieldErrors.email}</p>}
            {fieldErrors.password && <p>{fieldErrors.password}</p>}
          </div>
        )}
      </>
    );
  }

  // ═══ 注册视图：同风格卡片 ═══
  return (
    <div className="min-h-screen w-full bg-black relative overflow-hidden flex items-center justify-center">
      {/* 背景渐变 */}
      <div className="absolute inset-0 bg-gradient-to-b from-purple-500/30 via-purple-700/40 to-black" />
      <motion.div
        className="absolute top-0 left-1/2 -translate-x-1/2 w-[100vh] h-[60vh] rounded-b-full bg-purple-400/20 blur-[80px]"
        animate={{ opacity: [0.15, 0.3, 0.15], scale: [0.98, 1.02, 0.98] }}
        transition={{ duration: 8, repeat: Infinity, repeatType: "mirror" }}
      />

      {/* 卡片 */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.8 }}
        className="w-full max-w-sm relative z-10 px-6"
      >
        <div className="relative bg-black/40 backdrop-blur-xl rounded-2xl p-6 border border-white/[0.05] shadow-2xl overflow-hidden">
          <div className="absolute -inset-[0.5px] rounded-2xl bg-gradient-to-r from-white/5 via-white/10 to-white/5 pointer-events-none" />

          {/* 标题 */}
          <div className="text-center space-y-1 mb-5 relative">
            <motion.div
              initial={{ scale: 0.5, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              transition={{ type: "spring", duration: 0.8 }}
              className="mx-auto w-10 h-10 rounded-full border border-white/10 flex items-center justify-center relative overflow-hidden"
            >
              <span className="text-lg font-bold bg-clip-text text-transparent bg-gradient-to-b from-white to-white/70">
                R
              </span>
            </motion.div>
            <h1 className="text-xl font-bold bg-clip-text text-transparent bg-gradient-to-b from-white to-white/80">
              Create Account
            </h1>
            <p className="text-white/60 text-xs">
              注册以开始分析简历
            </p>
          </div>

          {/* 全局错误/成功提示 */}
          {error && (
            <div className="mb-4 p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
              {error}
            </div>
          )}
          {success && (
            <div className="mb-4 p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-sm">
              {success}
            </div>
          )}

          {/* 注册表单 */}
          <form onSubmit={handleRegister} className="space-y-4 relative">
            <RegisterInput
              id="reg-username"
              label="用户名"
              value={username}
              onChange={setUsername}
              placeholder="至少2个字符"
              error={fieldErrors.username}
              icon={User}
            />
            <RegisterInput
              id="reg-email"
              label="邮箱"
              type="email"
              value={regEmail}
              onChange={setRegEmail}
              placeholder="your@email.com"
              error={fieldErrors.regEmail}
              icon={Mail}
            />
            <RegisterInput
              id="reg-password"
              label="密码"
              type="password"
              value={regPassword}
              onChange={setRegPassword}
              placeholder="至少8位，需包含字母和数字"
              error={fieldErrors.regPassword}
              icon={Lock}
            />
            <RegisterInput
              id="reg-confirm"
              label="确认密码"
              type="password"
              value={regConfirm}
              onChange={setRegConfirm}
              placeholder="再输一遍"
              error={fieldErrors.regConfirm}
              icon={Lock}
            />

            <motion.button
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
              type="submit"
              disabled={loading}
              data-testid="register-submit-btn"
              className="w-full relative mt-2"
            >
              <div className="relative overflow-hidden bg-white text-black font-medium h-10 rounded-lg transition-all duration-300 flex items-center justify-center gap-1">
                {loading ? (
                  <div className="w-4 h-4 border-2 border-black/70 border-t-transparent rounded-full animate-spin" />
                ) : (
                  <span className="flex items-center justify-center gap-1 text-sm font-medium">
                    Sign Up
                    <ArrowRight className="w-3 h-3" />
                  </span>
                )}
              </div>
            </motion.button>

            {/* 返回登录 */}
            <p className="text-center text-xs text-white/60 mt-4">
              Already have an account?{" "}
              <button
                type="button"
                onClick={() => {
                  setTab("login");
                  setError("");
                  setFieldErrors({});
                  setPassword("");
                  setRegPassword("");
                  setRegConfirm("");
                }}
                className="text-white hover:text-white/70 transition-colors duration-300 font-medium cursor-pointer"
              >
                Log in
              </button>
            </p>
          </form>
        </div>
      </motion.div>
    </div>
  );
}
