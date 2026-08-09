import { useState, type FormEvent } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, LockSimple, Hash, Eye, EyeSlash } from "@phosphor-icons/react";
import { cn } from "@/lib/utils";

type TabType = "password" | "code";

interface Props {
  open: boolean;
  onClose: () => void;
  currentEmail: string;
}

export default function ChangePasswordDialog({ open, onClose, currentEmail }: Props) {
  const [tab, setTab] = useState<TabType>("password");
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [code, setCode] = useState("");
  const [showOld, setShowOld] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [loading, setLoading] = useState(false);
  const [sendCodeLoading, setSendCodeLoading] = useState(false);
  const [sendCodeCooldown, setSendCodeCooldown] = useState(0);
  const [focusedInput, setFocusedInput] = useState<string | null>(null);

  const PASSWORD_RE = /^(?=.*[a-zA-Z])(?=.*\d).{8,}$/;

  const handleSendCode = async () => {
    if (sendCodeCooldown > 0 || sendCodeLoading) return;
    setSendCodeLoading(true);
    try {
      const { sendCode } = await import("../api/auth");
      await sendCode(currentEmail);
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

    if (tab === "password") {
      if (!oldPassword) {
        setError("请输入旧密码");
        return;
      }
    } else {
      if (!code || code.length !== 6) {
        setError("请输入6位验证码");
        return;
      }
    }

    if (!newPassword || !PASSWORD_RE.test(newPassword)) {
      setError("新密码至少8位，需包含字母和数字");
      return;
    }
    if (newPassword !== confirmPassword) {
      setError("两次密码不一致");
      return;
    }

    setLoading(true);
    try {
      const { changePassword } = await import("../api/auth");
      await changePassword({
        mode: tab,
        old_password: tab === "password" ? oldPassword : undefined,
        verification_code: tab === "code" ? code : undefined,
        new_password: newPassword,
      });
      setSuccess("密码修改成功");
      setTimeout(onClose, 1000);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "修改失败，请稍后再试");
    } finally {
      setLoading(false);
    }
  };

  const resetState = () => {
    setTab("password");
    setOldPassword("");
    setNewPassword("");
    setConfirmPassword("");
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
            data-testid="change-password-dialog"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--color-border)]">
              <h2 className="text-lg font-semibold text-[var(--color-text)]">修改密码</h2>
              <button
                onClick={handleClose}
                className="text-[var(--color-text-muted)] hover:text-[var(--color-text)] transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleSubmit} className="p-5 space-y-4">
              {/* Tab切换 */}
              <div className="flex gap-2 p-1 bg-[var(--color-bg-secondary)] rounded-action">
                <button
                  type="button"
                  onClick={() => { setTab("password"); setError(""); }}
                  className={cn(
                    "flex-1 py-2 px-3 text-sm rounded-md transition-all",
                    tab === "password"
                      ? "bg-[var(--color-bg)] text-[var(--color-text)] shadow-sm"
                      : "text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)]"
                  )}
                >
                  旧密码验证
                </button>
                <button
                  type="button"
                  onClick={() => { setTab("code"); setError(""); }}
                  className={cn(
                    "flex-1 py-2 px-3 text-sm rounded-md transition-all",
                    tab === "code"
                      ? "bg-[var(--color-bg)] text-[var(--color-text)] shadow-sm"
                      : "text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)]"
                  )}
                >
                  邮箱验证码
                </button>
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

              {/* 旧密码输入 */}
              {tab === "password" && (
                <div className="relative">
                  <LockSimple className={cn(
                    "absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 transition-colors",
                    focusedInput === "oldPassword" ? "text-[var(--color-text)]" : "text-[var(--color-text-muted)]"
                  )} />
                  <input
                    type={showOld ? "text" : "password"}
                    value={oldPassword}
                    onChange={(e) => setOldPassword(e.target.value)}
                    onFocus={() => setFocusedInput("oldPassword")}
                    onBlur={() => setFocusedInput(null)}
                    placeholder="旧密码"
                    className="w-full h-10 pl-10 pr-10 bg-[var(--color-bg-secondary)] border border-[var(--color-border)] rounded-action text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:outline-none focus:border-[var(--color-primary)] transition-colors"
                  />
                  <button
                    type="button"
                    onClick={() => setShowOld(!showOld)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)]"
                  >
                    {showOld ? <EyeSlash className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
              )}

              {/* 验证码输入 */}
              {tab === "code" && (
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
              )}

              {/* 新密码输入 */}
              <div className="relative">
                <LockSimple className={cn(
                  "absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 transition-colors",
                  focusedInput === "newPassword" ? "text-[var(--color-text)]" : "text-[var(--color-text-muted)]"
                )} />
                <input
                  type={showNew ? "text" : "password"}
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  onFocus={() => setFocusedInput("newPassword")}
                  onBlur={() => setFocusedInput(null)}
                  placeholder="新密码（至少8位，含字母和数字）"
                  className="w-full h-10 pl-10 pr-10 bg-[var(--color-bg-secondary)] border border-[var(--color-border)] rounded-action text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:outline-none focus:border-[var(--color-primary)] transition-colors"
                />
                <button
                  type="button"
                  onClick={() => setShowNew(!showNew)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)]"
                >
                  {showNew ? <EyeSlash className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>

              {/* 确认新密码输入 */}
              <div className="relative">
                <LockSimple className={cn(
                  "absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 transition-colors",
                  focusedInput === "confirmPassword" ? "text-[var(--color-text)]" : "text-[var(--color-text-muted)]"
                )} />
                <input
                  type={showConfirm ? "text" : "password"}
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  onFocus={() => setFocusedInput("confirmPassword")}
                  onBlur={() => setFocusedInput(null)}
                  placeholder="确认新密码"
                  className="w-full h-10 pl-10 pr-10 bg-[var(--color-bg-secondary)] border border-[var(--color-border)] rounded-action text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:outline-none focus:border-[var(--color-primary)] transition-colors"
                />
                <button
                  type="button"
                  onClick={() => setShowConfirm(!showConfirm)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)]"
                >
                  {showConfirm ? <EyeSlash className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
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
