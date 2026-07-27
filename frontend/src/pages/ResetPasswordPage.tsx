import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { resetPassword } from "../api/auth";

export default function ResetPasswordPage() {
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token");
  const navigate = useNavigate();

  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  // token 缺失/无效时显示明确错误 + 重新申请入口
  if (!token) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[var(--color-bg)] px-4 py-12">
        <div className="w-full max-w-md">
          <div className="bg-white/5 backdrop-blur-xl border border-[var(--color-border)] rounded-2xl p-8 text-center">
            <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-red-500/10 border border-red-500/20 flex items-center justify-center text-3xl">
              ⚠️
            </div>
            <h2 className="text-xl font-semibold text-[var(--color-text)] mb-2">链接无效</h2>
            <p className="text-sm text-[var(--color-text-muted)] mb-6">
              重置链接缺少必要参数，可能已损坏或被截断。请重新申请密码重置。
            </p>
            <Link
              to="/forgot-password"
              className="inline-block px-5 py-2.5 rounded-xl text-sm font-semibold text-white
                bg-linear-to-r from-indigo-500 to-purple-600
                hover:brightness-110 transition-all duration-200 cursor-pointer"
            >
              重新申请重置链接
            </Link>
          </div>
        </div>
      </div>
    );
  }

  const validate = (): string | null => {
    if (newPassword.length < 8) return "密码至少8位，需包含字母和数字";
    if (!/[a-zA-Z]/.test(newPassword)) return "密码必须包含字母";
    if (!/\d/.test(newPassword)) return "密码必须包含数字";
    if (newPassword !== confirmPassword) return "两次密码不一致";
    return null;
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");

    const invalidReason = validate();
    if (invalidReason) {
      setError(invalidReason);
      return;
    }

    setLoading(true);
    try {
      await resetPassword(token, newPassword);
      // 重置成功跳转登录页（用户需要用新密码登录）
      navigate("/login", { replace: true });
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "重置失败，请稍后再试");
    } finally {
      setLoading(false);
    }
  };

  // 后端 400（token 无效/已使用/过期）时显示重新申请入口
  const showRetryLink = error.includes("无效") || error.includes("过期") || error.includes("已使用");

  return (
    <div className="min-h-screen flex items-center justify-center bg-[var(--color-bg)] px-4 py-12">
      <div className="w-full max-w-md">
        <div className="bg-white/5 backdrop-blur-xl border border-[var(--color-border)] rounded-2xl p-8">
          <h2 className="text-xl font-semibold text-[var(--color-text)] mb-2">重置密码</h2>
          <p className="text-sm text-[var(--color-text-muted)] mb-6">
            请输入新密码，重置成功后使用新密码登录
          </p>

          {error && (
            <div className="mb-4 p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm animate-shake">
              {error}
              {showRetryLink && (
                <Link
                  to="/forgot-password"
                  className="block mt-2 text-indigo-400 hover:text-indigo-300 transition-colors"
                >
                  重新申请重置链接 →
                </Link>
              )}
            </div>
          )}

          <form onSubmit={handleSubmit} noValidate className="space-y-4">
            <div className="space-y-1.5">
              <label htmlFor="reset-new-password" className="block text-sm font-medium text-[var(--color-text-secondary)]">
                新密码
              </label>
              <input
                id="reset-new-password"
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                placeholder="至少8位，需包含字母和数字"
                className="w-full px-4 py-3 rounded-xl text-sm text-[var(--color-text)]
                  bg-white/5 border border-[var(--color-border)] transition-all duration-200
                  placeholder:text-[var(--color-text-muted)]
                  focus:outline-none focus:ring-2 focus:ring-indigo-500/40
                  focus:border-indigo-500/50"
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="reset-confirm-password" className="block text-sm font-medium text-[var(--color-text-secondary)]">
                确认新密码
              </label>
              <input
                id="reset-confirm-password"
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder="再输一遍"
                className="w-full px-4 py-3 rounded-xl text-sm text-[var(--color-text)]
                  bg-white/5 border border-[var(--color-border)] transition-all duration-200
                  placeholder:text-[var(--color-text-muted)]
                  focus:outline-none focus:ring-2 focus:ring-indigo-500/40
                  focus:border-indigo-500/50"
              />
            </div>
            <button
              type="submit"
              disabled={loading}
              className="w-full py-3 mt-2 rounded-xl text-sm font-semibold text-white
                bg-linear-to-r from-indigo-500 to-purple-600
                hover:brightness-110 hover:shadow-lg hover:shadow-indigo-500/25
                active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed
                transition-all duration-200 cursor-pointer"
            >
              {loading ? "重置中..." : "重置密码"}
            </button>
          </form>

          <p className="text-center text-sm text-[var(--color-text-muted)] mt-6">
            <Link to="/login" className="text-indigo-400 hover:text-indigo-300 transition-colors">
              返回登录
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
