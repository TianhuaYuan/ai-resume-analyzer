import { useState, useRef, useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { ChevronDown, Key, Mail, User } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { useTheme } from "../context/ThemeContext";
import ChangePasswordDialog from "./ChangePasswordDialog";
import ChangeEmailDialog from "./ChangeEmailDialog";
import ChangeUsernameDialog from "./ChangeUsernameDialog";

function QuotaBadge() {
  const [quota, setQuota] = useState<{
    enabled: boolean;
    used: number;
    limit: number;
    remaining: number;
  } | null>(null);

  useEffect(() => {
    const fetch = () => {
      import("../api/qa").then(({ getQuota }) => {
        getQuota()
          .then((data) => setQuota(data))
          .catch(() => {});
      });
    };
    fetch();
    const handler = () => fetch();
    window.addEventListener("quota:refresh", handler);
    const interval = setInterval(fetch, 30000);
    return () => {
      window.removeEventListener("quota:refresh", handler);
      clearInterval(interval);
    };
  }, []);

  if (!quota?.enabled) return null;

  const isLow = quota.remaining < quota.limit * 0.1;
  const isMedium = quota.remaining < quota.limit * 0.3;

  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-1 text-[10px] font-mono-label rounded
        ${isLow ? "text-red-400 bg-red-500/10" : isMedium ? "text-yellow-400 bg-yellow-500/10" : "text-indigo-400 bg-indigo-500/10"}`}
      title={`今日额度: ${quota.used}/${quota.limit}`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${
        isLow ? "bg-red-400" : isMedium ? "bg-yellow-400" : "bg-indigo-400"
      }`} />
      <span className="tabular-nums">{quota.remaining}</span>
    </span>
  );
}

export default function Navbar() {
  const { user, logout, updateUser } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = useState(false);
  const [passwordDialogOpen, setPasswordDialogOpen] = useState(false);
  const [emailDialogOpen, setEmailDialogOpen] = useState(false);
  const [usernameDialogOpen, setUsernameDialogOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setMenuOpen(false);
      }
    };
    if (menuOpen) {
      document.addEventListener("mousedown", handleClickOutside);
      return () => document.removeEventListener("mousedown", handleClickOutside);
    }
  }, [menuOpen]);

  if (!user) return null;

  const menuItems = [
    {
      icon: <Key className="w-4 h-4" />,
      label: "修改密码",
      onClick: () => { setPasswordDialogOpen(true); setMenuOpen(false); },
      "data-testid": "menu-change-password",
    },
    {
      icon: <Mail className="w-4 h-4" />,
      label: "重新绑定邮箱",
      onClick: () => { setEmailDialogOpen(true); setMenuOpen(false); },
      "data-testid": "menu-change-email",
    },
    {
      icon: <User className="w-4 h-4" />,
      label: "修改用户名",
      onClick: () => { setUsernameDialogOpen(true); setMenuOpen(false); },
      "data-testid": "menu-change-username",
    },
  ];

  return (
    <>
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
          <QuotaBadge />

          <div className="relative" ref={menuRef}>
            <button
              onClick={() => setMenuOpen(!menuOpen)}
              className="flex items-center gap-1.5 text-[var(--color-text-secondary)] hover:text-[var(--color-text)] transition-colors cursor-pointer"
            >
              <span>{user.username}</span>
              <motion.div
                animate={{ rotate: menuOpen ? 180 : 0 }}
                transition={{ duration: 0.2 }}
              >
                <ChevronDown className="w-3.5 h-3.5" />
              </motion.div>
            </button>

            <AnimatePresence>
              {menuOpen && (
                <motion.div
                  initial={{ opacity: 0, y: -5, scale: 0.95 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, y: -5, scale: 0.95 }}
                  transition={{ duration: 0.15 }}
                  className="absolute right-0 top-full mt-2 w-48 bg-[var(--color-bg)] border border-[var(--color-border)] rounded-lg shadow-lg py-1 z-50"
                >
                  {menuItems.map((item) => (
                    <button
                      key={item.label}
                      onClick={item.onClick}
                      data-testid={item["data-testid"]}
                      className="w-full flex items-center gap-2.5 px-3 py-2 text-sm text-[var(--color-text-secondary)] hover:text-[var(--color-text)] hover:bg-[var(--color-bg-secondary)] transition-colors cursor-pointer"
                    >
                      {item.icon}
                      {item.label}
                    </button>
                  ))}
                </motion.div>
              )}
            </AnimatePresence>
          </div>

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

      <ChangePasswordDialog
        open={passwordDialogOpen}
        onClose={() => setPasswordDialogOpen(false)}
        currentEmail={user.email}
      />
      <ChangeEmailDialog
        open={emailDialogOpen}
        onClose={() => setEmailDialogOpen(false)}
        currentEmail={user.email}
        onSuccess={(newEmail) => updateUser({ email: newEmail })}
      />
      <ChangeUsernameDialog
        open={usernameDialogOpen}
        onClose={() => setUsernameDialogOpen(false)}
        currentUsername={user.username}
        onSuccess={(newUsername) => updateUser({ username: newUsername })}
      />
    </>
  );
}
