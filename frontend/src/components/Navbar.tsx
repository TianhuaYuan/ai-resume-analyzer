import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

export default function Navbar() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  if (!user) return null;

  return (
    <nav className="flex items-center justify-between px-6 py-3
      border-b border-white/6 bg-[#0f172a]/80 backdrop-blur-xl sticky top-0 z-40">
      <Link to="/" className="flex items-center gap-2.5 no-underline">
        <div className="w-7 h-7 rounded-lg bg-linear-to-br from-indigo-500 to-purple-600
          flex items-center justify-center">
          <span className="text-white text-xs font-bold">R</span>
        </div>
        <span className="text-sm font-semibold text-slate-200">
          AI Resume Analyzer
        </span>
      </Link>
      <div className="flex items-center gap-4 text-sm">
        <span className="text-slate-400">{user.username}</span>
        <button
          onClick={handleLogout}
          className="text-slate-500 hover:text-red-400 transition-colors cursor-pointer"
        >
          退出
        </button>
      </div>
    </nav>
  );
}
