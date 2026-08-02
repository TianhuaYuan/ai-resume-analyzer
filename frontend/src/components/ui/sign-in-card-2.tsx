import { useState, type FormEvent, type MouseEvent } from "react";
import {
  motion,
  AnimatePresence,
  useMotionValue,
  useTransform,
} from "framer-motion";
import { EnvelopeSimple, LockSimple, Eye, EyeClosed, ArrowRight } from "@phosphor-icons/react";
import { cn } from "@/lib/utils";

export interface SignInCard2Props {
  email: string;
  password: string;
  onEmailChange: (v: string) => void;
  onPasswordChange: (v: string) => void;
  onSubmit: (e: FormEvent) => void;
  isLoading?: boolean;
  onForgotPassword?: () => void;
  onSignUp?: () => void;
}

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

export function SignInCard2({
  email,
  password,
  onEmailChange,
  onPasswordChange,
  onSubmit,
  isLoading = false,
  onForgotPassword,
  onSignUp,
}: SignInCard2Props) {
  const [showPassword, setShowPassword] = useState(false);
  const [focusedInput, setFocusedInput] = useState<string | null>(null);
  const [rememberMe, setRememberMe] = useState(false);

  // 3D 卡片倾斜效果
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

  return (
    <div className="min-h-screen w-full bg-[var(--color-bg)] relative overflow-hidden flex items-center justify-center">
      {/* 背景渐变：淡品牌色径向氛围 */}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_60%_50%_at_50%_-10%,rgba(0,113,227,0.10),transparent_70%)]" />

      {/* 顶部径向光晕 */}
      <motion.div
        className="absolute top-0 left-1/2 -translate-x-1/2 w-[100vh] h-[60vh] rounded-b-full bg-brand/15 blur-[80px]"
        animate={{ opacity: [0.15, 0.3, 0.15], scale: [0.98, 1.02, 0.98] }}
        transition={{ duration: 8, repeat: Infinity, repeatType: "mirror" }}
      />
      <motion.div
        className="absolute bottom-0 left-1/2 -translate-x-1/2 w-[90vh] h-[90vh] rounded-t-full bg-brand/15 blur-[60px]"
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
          <div className="relative glass-card p-6 shadow-[0_20px_60px_rgba(0,0,0,0.08)] overflow-hidden">
            {/* 卡片边框流光 */}
            <div className="absolute -inset-[0.5px] rounded-[24px] bg-gradient-to-r from-transparent via-brand/10 to-transparent pointer-events-none" />

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
                className="text-[22px] font-bold display-tight text-[var(--color-text)]"
              >
                欢迎回来
              </motion.h1>

              <motion.p
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: 0.3 }}
                className="text-[var(--color-text-muted)] text-xs"
              >
                登录以继续使用 轻舟简历
              </motion.p>
            </div>

            {/* 登录表单 */}
            <form onSubmit={onSubmit} className="space-y-4 relative">
              <div className="space-y-3">
                {/* 邮箱输入 */}
                <div
                  className={cn(
                    "relative transition-transform duration-200",
                    focusedInput === "email" && "scale-[1.02]"
                  )}
                >
                  <div className="relative flex items-center overflow-hidden rounded-xl">
                    <EnvelopeSimple
                      className={cn(
                        "absolute left-3 w-4 h-4 transition-colors duration-300",
                        focusedInput === "email" ? "text-brand" : "text-[var(--color-text-muted)]"
                      )}
                    />
                    <Input
                      type="email"
                      placeholder="邮箱地址"
                      value={email}
                      onChange={(e) => onEmailChange(e.target.value)}
                      onFocus={() => setFocusedInput("email")}
                      onBlur={() => setFocusedInput(null)}
                      className="w-full bg-[#F2F2F7] border-transparent focus:border-brand/40 text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] h-10 transition-all duration-300 pl-10 pr-3 focus:bg-white rounded-xl focus:ring-4 focus:ring-brand/15"
                    />
                  </div>
                </div>

                {/* 密码输入 */}
                <div
                  className={cn(
                    "relative transition-transform duration-200",
                    focusedInput === "password" && "scale-[1.02]"
                  )}
                >
                  <div className="relative flex items-center overflow-hidden rounded-xl">
                    <LockSimple
                      className={cn(
                        "absolute left-3 w-4 h-4 transition-colors duration-300",
                        focusedInput === "password" ? "text-brand" : "text-[var(--color-text-muted)]"
                      )}
                    />
                    <Input
                      type={showPassword ? "text" : "password"}
                      placeholder="密码"
                      value={password}
                      onChange={(e) => onPasswordChange(e.target.value)}
                      onFocus={() => setFocusedInput("password")}
                      onBlur={() => setFocusedInput(null)}
                      className="w-full bg-[#F2F2F7] border-transparent focus:border-brand/40 text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] h-10 transition-all duration-300 pl-10 pr-10 focus:bg-white rounded-xl focus:ring-4 focus:ring-brand/15"
                    />
                    <button
                      type="button"
                      aria-label="toggle password visibility"
                      data-testid="password-toggle"
                      onClick={() => setShowPassword(!showPassword)}
                      className="absolute right-3 cursor-pointer"
                    >
                      {showPassword ? (
                        <Eye className="w-4 h-4 text-[var(--color-text-muted)] hover:text-[var(--color-text)] transition-colors duration-300" />
                      ) : (
                        <EyeClosed className="w-4 h-4 text-[var(--color-text-muted)] hover:text-[var(--color-text)] transition-colors duration-300" />
                      )}
                    </button>
                  </div>
                </div>
              </div>

              {/* 记住我 & 忘记密码 */}
              <div className="flex items-center justify-between pt-1">
                <div className="flex items-center space-x-2">
                  <input
                    id="remember-me"
                    type="checkbox"
                    checked={rememberMe}
                    onChange={(e) => setRememberMe(e.target.checked)}
                    className="appearance-none h-4 w-4 rounded border border-[var(--color-border)] bg-[var(--color-bg-secondary)] checked:bg-brand checked:border-brand focus:outline-none focus:ring-2 focus:ring-brand/25 transition-all duration-200"
                  />
                  <label
                    htmlFor="remember-me"
                    className="text-xs text-[var(--color-text-secondary)] hover:text-[var(--color-text)] transition-colors duration-200 cursor-pointer"
                  >
                    记住我
                  </label>
                </div>

                <button
                  type="button"
                  onClick={onForgotPassword}
                  className="text-xs text-brand hover:text-[#0077ed] transition-colors duration-200 cursor-pointer"
                >
                  忘记密码？
                </button>
              </div>

              {/* 登录按钮 */}
              <motion.button
                whileHover={{ scale: 1.02 }}
                whileTap={{ scale: 0.98 }}
                type="submit"
                disabled={isLoading}
                data-testid="submit-btn"
                className="w-full relative mt-5"
              >
                <div className="relative overflow-hidden bg-brand text-white font-medium h-10 rounded-full transition-all duration-300 flex items-center justify-center shadow-[0_8px_24px_rgba(0,113,227,0.25)] hover:bg-[#0077ed] hover:shadow-[0_12px_32px_rgba(0,113,227,0.35)]">
                  <AnimatePresence mode="wait">
                    {isLoading ? (
                      <motion.div
                        key="loading"
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        className="flex items-center justify-center"
                      >
                        <div className="w-4 h-4 border-2 border-white/70 border-t-transparent rounded-full animate-spin" />
                      </motion.div>
                    ) : (
                      <motion.span
                          key="button-text"
                          initial={{ opacity: 0 }}
                          animate={{ opacity: 1 }}
                          exit={{ opacity: 0 }}
                          className="flex items-center justify-center gap-1 text-sm font-medium"
                        >
                          登录
                          <ArrowRight className="w-3 h-3" />
                        </motion.span>
                    )}
                  </AnimatePresence>
                </div>
              </motion.button>

              {/* 注册链接 */}
              <motion.p
                className="text-center text-xs text-[var(--color-text-muted)] mt-4"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: 0.5 }}
              >
                还没有账号？{" "}
                <button
                  type="button"
                  onClick={onSignUp}
                  className="text-brand hover:text-[#0077ed] transition-colors duration-300 font-medium cursor-pointer"
                >
                  注册
                </button>
              </motion.p>
            </form>
          </div>
        </motion.div>
      </motion.div>
    </div>
  );
}

export default SignInCard2;
