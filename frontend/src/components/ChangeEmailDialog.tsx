import { useState, type FormEvent } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, Mail, Hash } from "lucide-react";
import { cn } from "@/lib/utils";

interface Props {
  open: boolean;
  onClose: () => void;
  currentEmail: string;
  onSuccess?: (newEmail: string) => void;
}

export default function ChangeEmailDialog({ open, onClose, currentEmail, onSuccess }: Props) {
  const [newEmail, setNewEmail] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [loading, setLoading] = useState(false);
  const [sendCodeLoading, setSendCodeLoading] = useState(false);
  const [sendCodeCooldown, setSendCodeCooldown] = useState(0);
  const [focusedInput, setFocusedInput] = useState<string | null>(null);

  const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

  const handleSendCode = async () => {
    if (sendCodeCooldown > 0 || sendCodeLoading) return;
    if (!newEmail.trim()) {
      setError("请输入新邮箱");
      return;
    }
    if (!EMAIL_RE.test(newEmail.trim())) {
      setError("邮箱格式不合法");
      return;
    }
    if (newEmail.trim() === currentEmail) {
      setError("新邮箱不能与当前邮箱相同");
      return;
    }

    setSendCodeLoading(true);
    try {
      const { sendCode } = await import("../api/auth");
      await sendCode(newEmail.trim());
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

    if (!newEmail.trim()) {
      setError("请输入新邮箱");
      return;
    }
    if (!EMAIL_RE.test(newEmail.trim())) {
      setError("邮箱格式不合法");
      return;
    }
    if (newEmail.trim() === currentEmail) {
      setError("新邮箱不能与当前邮箱相同");
      return;
    }
    if (!code || code.length !== 6) {
      setError("请输入6位验证码");
      return;
    }

    setLoading(true);
    try {
      const { changeEmail } = await import("../api/auth");
      await changeEmail(newEmail.trim(), code);
      setSuccess("邮箱修改成功");
      onSuccess?.(newEmail.trim());
      setTimeout(onClose, 1000);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "修改失败，请稍后再试");
    } finally {
      setLoading(false);
    }
  };

  const resetState = () => {
    setNewEmail("");
    setCode("");
    setError("");
    setSuccess("");
  };

  const handleClose = () => {
    resetState();
    onClose();
  };

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4"
          onClick={handleClose}
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 20 }}
            transition={{ duration: 0.2 }}
            className="w-full max-w-md bg-[var(--color-bg)] border border-[var(--color-border)] rounded-input shadow-2xl overflow-hidden animate-fade-in-up motion-reduce:animate-none"
            data-testid="change-email-dialog"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--color-border)]">
              <h2 className="text-lg font-semibold text-[var(--color-text)]">重新绑定邮箱</h2>
              <button
                onClick={handleClose}
                className="text-[var(--color-text-muted)] hover:text-[var(--color-text)] transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleSubmit} className="p-5 space-y-4">
              <div className="text-sm text-[var(--color-text-secondary)]">
                当前邮箱：<span className="text-[var(--color-text)]">{currentEmail}</span>
              </div>

              {error && (
                <div className="p-3 rounded-action bg-danger/10 border border-danger/20 text-danger text-sm">
                  {error}
                </div>
              )}
              {success && (
                <div className="p-3 rounded-action bg-success/10 border border-success/20 text-success text-sm">
                  {success}
                </div>
              )}

              {/* 新邮箱输入 */}
              <div className="relative">
                <Mail className={cn(
                  "absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 transition-colors",
                  focusedInput === "newEmail" ? "text-[var(--color-text)]" : "text-[var(--color-text-muted)]"
                )} />
                <input
                  type="email"
                  value={newEmail}
                  onChange={(e) => setNewEmail(e.target.value)}
                  onFocus={() => setFocusedInput("newEmail")}
                  onBlur={() => setFocusedInput(null)}
                  placeholder="新邮箱地址"
                  className="w-full h-10 pl-10 pr-3 bg-[var(--color-bg-secondary)] border border-[var(--color-border)] rounded-action text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:outline-none focus:border-[var(--color-primary)] transition-colors"
                />
              </div>

              {/* 验证码输入 + 发送按钮 */}
              <div className="flex gap-2">
                <div className="flex-1 relative">
                  <Hash className={cn(
                    "absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 transition-colors",
                    focusedInput === "code" ? "text-[var(--color-text)]" : "text-[var(--color-text-muted)]"
                  )} />
                  <input
                    type="text"
                    value={code}
                    onChange={(e) => setCode(e.target.value)}
                    onFocus={() => setFocusedInput("code")}
                    onBlur={() => setFocusedInput(null)}
                    placeholder="6位验证码"
                    maxLength={6}
                    className="w-full h-10 pl-10 pr-3 bg-[var(--color-bg-secondary)] border border-[var(--color-border)] rounded-action text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:outline-none focus:border-[var(--color-primary)] transition-colors"
                  />
                </div>
                <button
                  type="button"
                  disabled={sendCodeLoading || sendCodeCooldown > 0}
                  onClick={handleSendCode}
                  className="px-4 py-2 bg-[var(--color-bg-secondary)] hover:bg-[var(--color-bg-tertiary)] text-[var(--color-text)] text-sm rounded-action transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {sendCodeLoading ? "发送中..." : sendCodeCooldown > 0 ? `${sendCodeCooldown}s` : "发送"}
                </button>
              </div>

              <motion.button
                whileHover={{ scale: 1.02 }}
                whileTap={{ scale: 0.98 }}
                type="submit"
                disabled={loading}
                className="w-full h-10 bg-[var(--color-primary)] text-white font-medium rounded-action transition-colors hover:opacity-90 disabled:opacity-50"
              >
                {loading ? "提交中..." : "确认修改"}
              </motion.button>
            </form>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
