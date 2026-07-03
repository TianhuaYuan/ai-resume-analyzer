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
    <nav className="flex items-center justify-between px-6 py-3 border-b border-gray-200 bg-white">
      <Link to="/" className="text-lg font-semibold text-gray-800 no-underline">
        AI 简历分析
      </Link>
      <div className="flex items-center gap-4 text-sm text-gray-600">
        <span>{user.username}</span>
        <button
          onClick={handleLogout}
          className="text-gray-500 hover:text-red-600 transition-colors cursor-pointer"
        >
          退出
        </button>
      </div>
    </nav>
  );
}
