import { useState, type FormEvent, type MouseEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  motion,
  AnimatePresence,
  useMotionValue,
  useTransform,
} from "framer-motion";
import { EnvelopeSimple, LockSimple, Hash, ArrowRight } from "@phosphor-icons/react";
import { forgotPassword, sendCode } from "../api/auth";
import { cn } from "@/lib/utils";

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        "flex h-9 w-full min-w-0 rounded-md border bg-transparent px-3 py-1 text-base shadow-xs transition-[color,box-shadow] outline-none md:text-sm",
        "focus-visible:border-ring focus-visible:ring-[3px]",
        className
      )}
      {...props}
    />
  );
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [verificationCode, setVerificationCode] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [loading, setLoading] = useState(false);
  const [sendCodeLoading, setSendCodeLoading] = useState(false);
  const [sendCodeCooldown, setSendCodeCooldown] = useState(0);
  const [focusedInput, setFocusedInput] = useState<string | null>(null);
  const navigate = useNavigate();

  const mouseX = useMotionValue(0);
  const mouseY = useMotionValue(0);
  const rotateX = useTransform(mouseY, [-300, 300], [8, -8]);
  const rotateY = useTransform(mouseX, [-300, 300], [-8, 8]);

  const handleMouseMove = (e: MouseEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    mouseX.set(e.clientX - rect.left - rect.width / 2);
    mouseY.set(e.clientY - rect.top - rect.height / 2);
  };

  const handleMouseLeave = () => {
    mouseX.set(0);
    mouseY.set(0);
  };

  const handleSendCode = async () => {
    if (sendCodeCooldown > 0 || sendCodeLoading) return;
    if (!email.trim()) {
      setError("请先输入邮箱");
      return;
    }
    if (!EMAIL_RE.test(email.trim())) {
      setError("邮箱格式不合法");
      return;
    }

    setSendCodeLoading(true);
    try {
      await sendCode(email.trim());
      setSuccess("验证码已发送");
      setError("");
      setSendCodeCooldown(60);
      const timer = setInterval(() => {
        setSendCodeCooldown((prev) => {
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

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setSuccess("");

    if (!email.trim()) {
      setError("请输入邮箱");
      return;
    }
    if (!EMAIL_RE.test(email.trim())) {
      setError("邮箱格式不合法");
      return;
    }
    if (!verificationCode || verificationCode.length !== 6) {
      setError("请输入6位验证码");
      return;
    }
    if (!newPassword || newPassword.length < 8) {
      setError("新密码至少8位，需包含字母和数字");
      return;
    }
    if (newPassword !== confirmPassword) {
      setError("两次密码不一致");
      return;
    }

    setLoading(true);
    try {
      await forgotPassword(email.trim(), verificationCode, newPassword);
      setSuccess("密码已重置，3秒后跳转到登录页");
      setTimeout(() => navigate("/login", { state: { email: email.trim() } }), 3000);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "重置失败，请稍后再试");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen w-full bg-black relative overflow-hidden flex items-center justify-center">
      {/* 背景渐变 */}
      <div className="absolute inset-0 bg-gradient-to-b from-purple-500/30 via-purple-700/40 to-black" />
      {/* 顶部径向光晕 */}
      <motion.div
        className="absolute top-0 left-1/2 -translate-x-1/2 w-[100vh] h-[60vh] rounded-b-full bg-purple-400/20 blur-[80px]"
        animate={{ opacity: [0.15, 0.3, 0.15], scale: [0.98, 1.02, 0.98] }}
        transition={{ duration: 8, repeat: Infinity, repeatType: "mirror" }}
      />
      <motion.div
        className="absolute bottom-0 left-1/2 -translate-x-1/2 w-[90vh] h-[90vh] rounded-t-full bg-purple-400/20 blur-[60px]"
        animate={{ opacity: [0.3, 0.5, 0.3], scale: [1, 1.1, 1] }}
        transition={{ duration: 6, repeat: Infinity, repeatType: "mirror", delay: 1 }}
      />

      {/* 卡片容器 */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.8 }}
        className="w-full max-w-sm relative z-10 px-6"
        style={{ perspective: 1500 }}
      >
        <motion.div
          style={{ rotateX, rotateY }}
          onMouseMove={handleMouseMove}
          onMouseLeave={handleMouseLeave}
        >
          {/* 玻璃卡片 */}
          <div className="relative bg-black/40 backdrop-blur-xl rounded-2xl p-6 border border-white/[0.05] shadow-2xl overflow-hidden">
            {/* 卡片边框流光 */}
            <div className="absolute -inset-[0.5px] rounded-2xl bg-gradient-to-r from-white/5 via-white/10 to-white/5 pointer-events-none" />

            {/* Logo 和标题 */}
            <div className="text-center space-y-1 mb-5 relative">
              <motion.div
                initial={{ scale: 0.5, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                transition={{ type: "spring", duration: 0.8 }}
                className="mx-auto w-10 h-10 flex items-center justify-center"
              >
                <svg viewBox="0 0 64 64" className="w-10 h-10">
                  <polygon points="32,6 54,18 32,30 10,18" fill="#F5C547"/>
                  <polygon points="10,18 32,30 32,54 10,42" fill="#38D4D4"/>
                  <polygon points="32,30 54,18 54,42 32,54" fill="#8B5CF6"/>
                </svg>
              </motion.div>

              <motion.h1
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.2 }}
                className="text-xl font-bold bg-clip-text text-transparent bg-gradient-to-b from-white to-white/80"
              >
                重置密码
              </motion.h1>

              <motion.p
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: 0.3 }}
                className="text-white/60 text-xs"
              >
                输入注册邮箱，获取验证码后直接设置新密码
              </motion.p>
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

            {/* 表单 */}
            <form onSubmit={handleSubmit} className="space-y-4 relative">
              {/* 邮箱输入 */}
              <div
                className={cn(
                  "relative transition-transform duration-200",
                  focusedInput === "email" && "scale-[1.02]"
                )}
              >
                <div className="relative flex items-center overflow-hidden rounded-lg">
                  <EnvelopeSimple
                    className={cn(
                      "absolute left-3 w-4 h-4 transition-colors duration-300",
                      focusedInput === "email" ? "text-white" : "text-white/40"
                    )}
                  />
                  <Input
                    id="forgot-email"
                    type="email"
                    required
                    aria-label="邮箱"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    onFocus={() => setFocusedInput("email")}
                    onBlur={() => setFocusedInput(null)}
                    placeholder="邮箱地址"
                    className="w-full bg-white/5 border-white/10 focus:border-white/20 text-white placeholder:text-white/30 h-10 transition-all duration-300 pl-10 pr-3 focus:bg-white/10 rounded-lg"
                  />
                </div>
              </div>

              {/* 验证码输入 + 发送按钮 */}
              <div className="flex gap-2">
                <div className="flex-1">
                  <div
                    className={cn(
                      "relative transition-transform duration-200",
                      focusedInput === "code" && "scale-[1.02]"
                    )}
                  >
                    <div className="relative flex items-center overflow-hidden rounded-lg">
                      <Hash
                        className={cn(
                          "absolute left-3 w-4 h-4 transition-colors duration-300",
                          focusedInput === "code" ? "text-white" : "text-white/40"
                        )}
                      />
                      <Input
                        id="forgot-code"
                        type="text"
                        required
                        aria-label="验证码"
                        value={verificationCode}
                        onChange={(e) => setVerificationCode(e.target.value)}
                        onFocus={() => setFocusedInput("code")}
                        onBlur={() => setFocusedInput(null)}
                        placeholder="6位数字"
                        maxLength={6}
                        className="w-full bg-white/5 border-white/10 focus:border-white/20 text-white placeholder:text-white/30 h-10 transition-all duration-300 pl-10 pr-3 focus:bg-white/10 rounded-lg"
                      />
                    </div>
                  </div>
                </div>
                <button
                  type="button"
                  disabled={sendCodeLoading || sendCodeCooldown > 0}
                  onClick={handleSendCode}
                  className="px-4 py-2 bg-white/10 hover:bg-white/20 text-white text-sm rounded-lg transition-colors duration-300 flex items-center justify-center self-end mt-0"
                >
                  {sendCodeLoading ? (
                    <div className="w-4 h-4 border-2 border-white/70 border-t-transparent rounded-full animate-spin" />
                  ) : sendCodeCooldown > 0 ? (
                    `${sendCodeCooldown}s`
                  ) : (
                    "发送"
                  )}
                </button>
              </div>

              {/* 新密码输入 */}
              <div
                className={cn(
                  "relative transition-transform duration-200",
                  focusedInput === "newPassword" && "scale-[1.02]"
                )}
              >
                <div className="relative flex items-center overflow-hidden rounded-lg">
                  <LockSimple
                    className={cn(
                      "absolute left-3 w-4 h-4 transition-colors duration-300",
                      focusedInput === "newPassword" ? "text-white" : "text-white/40"
                    )}
                  />
                  <Input
                    id="forgot-new-password"
                    type="password"
                    required
                    aria-label="新密码"
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    onFocus={() => setFocusedInput("newPassword")}
                    onBlur={() => setFocusedInput(null)}
                    placeholder="新密码"
                    className="w-full bg-white/5 border-white/10 focus:border-white/20 text-white placeholder:text-white/30 h-10 transition-all duration-300 pl-10 pr-3 focus:bg-white/10 rounded-lg"
                  />
                </div>
              </div>

              {/* 确认新密码输入 */}
              <div
                className={cn(
                  "relative transition-transform duration-200",
                  focusedInput === "confirmPassword" && "scale-[1.02]"
                )}
              >
                <div className="relative flex items-center overflow-hidden rounded-lg">
                  <LockSimple
                    className={cn(
                      "absolute left-3 w-4 h-4 transition-colors duration-300",
                      focusedInput === "confirmPassword" ? "text-white" : "text-white/40"
                    )}
                  />
                  <Input
                    id="forgot-confirm-password"
                    type="password"
                    required
                    aria-label="确认新密码"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    onFocus={() => setFocusedInput("confirmPassword")}
                    onBlur={() => setFocusedInput(null)}
                    placeholder="确认新密码"
                    className="w-full bg-white/5 border-white/10 focus:border-white/20 text-white placeholder:text-white/30 h-10 transition-all duration-300 pl-10 pr-3 focus:bg-white/10 rounded-lg"
                  />
                </div>
              </div>

            {/* 重置密码按钮 */}
            <motion.button
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
              type="submit"
              disabled={loading}
              data-testid="forgot-password-submit"
              className="w-full relative mt-5"
            >
              <div className="relative overflow-hidden bg-white text-black font-medium h-10 rounded-lg transition-all duration-300 flex items-center justify-center">
                <AnimatePresence mode="wait">
                  {loading ? (
                    <motion.div
                      key="loading"
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0 }}
                      className="flex items-center justify-center"
                    >
                      <div className="w-4 h-4 border-2 border-black/70 border-t-transparent rounded-full animate-spin" />
                    </motion.div>
                  ) : (
                    <motion.span
                      key="button-text"
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0 }}
                      className="flex items-center justify-center gap-1 text-sm font-medium"
                    >
                      重置密码
                      <ArrowRight className="w-3 h-3" />
                    </motion.span>
                  )}
                </AnimatePresence>
              </div>
            </motion.button>

            {/* 返回登录 */}
            <motion.p
              className="text-center text-xs text-white/60 mt-4"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.5 }}
            >
              <Link
                to="/login"
                className="text-white hover:text-white/70 transition-colors duration-300 font-medium"
              >
                返回登录
              </Link>
            </motion.p>
          </form>
        </div>
        </motion.div>
      </motion.div>
    </div>
  );
}
