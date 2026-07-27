import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { forgotPassword } from "../api/auth";

// 简单邮箱正则：前端只做粗校验，后端 Pydantic EmailStr 是权威校验
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setSuccess("");

    // 前端校验：空值 + 邮箱格式
    if (!email.trim()) {
      setError("请输入邮箱");
      return;
    }
    if (!EMAIL_RE.test(email.trim())) {
      setError("邮箱格式不合法");
      return;
    }

    setLoading(true);
    try {
      const detail = await forgotPassword(email.trim());
      setSuccess(detail);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "请求失败，请稍后再试");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-[var(--color-bg)] px-4 py-12">
      <div className="w-full max-w-md">
        <div className="bg-white/5 backdrop-blur-xl border border-[var(--color-border)] rounded-2xl p-8">
          <h2 className="text-xl font-semibold text-[var(--color-text)] mb-2">忘记密码</h2>
          <p className="text-sm text-[var(--color-text-muted)] mb-6">
            输入注册邮箱，我们将向该邮箱发送密码重置链接
          </p>

          {error && (
            <div className="mb-4 p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm animate-shake">
              {error}
            </div>
          )}
          {success && (
            <div className="mb-4 p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-sm">
              {success}
            </div>
          )}

          <form onSubmit={handleSubmit} noValidate className="space-y-4">
            <div className="space-y-1.5">
              <label htmlFor="forgot-email" className="block text-sm font-medium text-[var(--color-text-secondary)]">
                邮箱
              </label>
              <input
                id="forgot-email"
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="your@email.com"
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
              {loading ? "发送中..." : "发送重置链接"}
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
