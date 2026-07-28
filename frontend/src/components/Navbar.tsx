import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { useTheme } from "../context/ThemeContext";

export default function Navbar() {
  const { user, logout } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const navigate = useNavigate();

  const handleLogout = async () => {
    // await 后端撤销 JTI，再导航。POST 失败也被 auth.ts 静默吞掉，
    // 用户体感登出成功，最坏情况 token 30min 后自然过期。
    await logout();
    navigate("/login");
  };

  if (!user) return null;

  return (
    <nav className="flex items-center justify-between px-6 py-3
      border-b border-[var(--color-border)] bg-[var(--color-bg)] sticky top-0 z-40">
      <Link to="/" className="flex items-center gap-2.5 no-underline">
        <svg viewBox="0 0 64 64" className="w-7 h-7">
          <polygon points="32,6 54,18 32,30 10,18" fill="#F5C547"/>
          <polygon points="10,18 32,30 32,54 10,42" fill="#38D4D4"/>
          <polygon points="32,30 54,18 54,42 32,54" fill="#8B5CF6"/>
        </svg>
        <span className="text-sm font-semibold text-[var(--color-text)]">
          AI Resume Analyzer
        </span>
      </Link>
      <div className="flex items-center gap-4 text-sm">
        <span className="text-[var(--color-text-secondary)]">{user.username}</span>
        <button
          onClick={toggleTheme}
          title={theme === "dark" ? "切换到亮色模式" : "切换到暗色模式"}
          className="text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)] transition-colors cursor-pointer"
        >
          {theme === "dark" ? "☀️" : "🌙"}
        </button>
        <button
          onClick={handleLogout}
          className="text-[var(--color-text-muted)] hover:text-red-400 transition-colors cursor-pointer"
        >
          退出
        </button>
      </div>
    </nav>
  );
}
