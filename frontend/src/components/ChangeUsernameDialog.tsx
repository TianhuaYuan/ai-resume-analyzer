import { useState, type FormEvent } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, User } from "lucide-react";
import { cn } from "@/lib/utils";

interface Props {
  open: boolean;
  onClose: () => void;
  currentUsername: string;
  onSuccess?: (newUsername: string) => void;
}

export default function ChangeUsernameDialog({ open, onClose, currentUsername, onSuccess }: Props) {
  const [newUsername, setNewUsername] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [loading, setLoading] = useState(false);
  const [focusedInput, setFocusedInput] = useState<string | null>(null);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setSuccess("");

    const trimmed = newUsername.trim();
    if (!trimmed) {
      setError("请输入新用户名");
      return;
    }
    if (trimmed.length < 2) {
      setError("用户名至少2个字符");
      return;
    }
    if (trimmed.length > 50) {
      setError("用户名最多50个字符");
      return;
    }
    if (trimmed === currentUsername) {
      setError("新用户名不能与当前用户名相同");
      return;
    }

    setLoading(true);
    try {
      const { changeUsername } = await import("../api/auth");
      await changeUsername(trimmed);
      setSuccess("用户名修改成功");
      onSuccess?.(trimmed);
      setTimeout(onClose, 1000);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "修改失败，请稍后再试");
    } finally {
      setLoading(false);
    }
  };

  const resetState = () => {
    setNewUsername("");
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
            className="w-full max-w-md bg-[var(--color-bg)] border border-[var(--color-border)] rounded-2xl shadow-2xl overflow-hidden"
            data-testid="change-username-dialog"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--color-border)]">
              <h2 className="text-lg font-semibold text-[var(--color-text)]">修改用户名</h2>
              <button
                onClick={handleClose}
                className="text-[var(--color-text-muted)] hover:text-[var(--color-text)] transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleSubmit} className="p-5 space-y-4">
              <div className="text-sm text-[var(--color-text-secondary)]">
                当前用户名：<span className="text-[var(--color-text)]">{currentUsername}</span>
              </div>

              {error && (
                <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
                  {error}
                </div>
              )}
              {success && (
                <div className="p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-sm">
                  {success}
                </div>
              )}

              {/* 新用户名输入 */}
              <div className="relative">
                <User className={cn(
                  "absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 transition-colors",
                  focusedInput === "newUsername" ? "text-[var(--color-text)]" : "text-[var(--color-text-muted)]"
                )} />
                <input
                  type="text"
                  value={newUsername}
                  onChange={(e) => setNewUsername(e.target.value)}
                  onFocus={() => setFocusedInput("newUsername")}
                  onBlur={() => setFocusedInput(null)}
                  placeholder="新用户名"
                  className="w-full h-10 pl-10 pr-3 bg-[var(--color-bg-secondary)] border border-[var(--color-border)] rounded-lg text-sm text-[var(--color-text)] placeholder:text-[var(--color-text-muted)] focus:outline-none focus:border-[var(--color-primary)] transition-colors"
                />
              </div>

              <motion.button
                whileHover={{ scale: 1.02 }}
                whileTap={{ scale: 0.98 }}
                type="submit"
                disabled={loading}
                className="w-full h-10 bg-[var(--color-primary)] text-white font-medium rounded-lg transition-colors hover:opacity-90 disabled:opacity-50"
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
