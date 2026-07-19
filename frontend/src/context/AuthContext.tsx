import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  useRef,
  type ReactNode,
} from "react";
import { login as loginApi, register as registerApi, logout as clearTokens } from "../api/auth";
import { refreshToken, clearSessionAndRedirect, notifySessionWarning } from "../api/client";
import { safeDecodeJwt } from "../utils/jwt";

interface User {
  id: number;
  username: string;
  email: string;
}

/** 会话弹窗类型：null=不弹、expired=已过期、warning=即将过期 */
export type SessionDialogType = "expired" | "warning" | null;

interface AuthCtx {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (
    username: string,
    email: string,
    password: string,
    password_confirm: string
  ) => Promise<void>;
  logout: () => Promise<void>;
  // Task 5：会话弹窗状态
  sessionDialog: SessionDialogType;
  sessionRemainingSeconds: number;
  sessionExtending: boolean;
  handleSessionGoLogin: () => void;
  handleSessionExtend: () => Promise<void>;
  handleSessionIgnore: () => void;
}

const AuthContext = createContext<AuthCtx | undefined>(undefined);

// 提前 5 分钟（300 秒）预警即将过期
const WARNING_BEFORE_SECONDS = 300;

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  // Task 5：会话弹窗状态
  const [sessionDialog, setSessionDialog] = useState<SessionDialogType>(null);
  const [sessionRemainingSeconds, setSessionRemainingSeconds] = useState(0);
  const [sessionExtending, setSessionExtending] = useState(false);
  const warningShownRef = useRef(false); // 本次会话内 warning 只弹一次

  // ── 启动时从 token 解码 user 信息 ──────────────────────
  useEffect(() => {
    const token = localStorage.getItem("access_token");
    if (token) {
      const payload = safeDecodeJwt(token);
      if (payload && payload.exp != null && payload.exp * 1000 > Date.now()) {
        setUser({
          id: Number(payload.sub),
          username: payload.username || "",
          email: payload.email || "",
        });
      } else {
        clearTokens();
      }
    }
    setLoading(false);
  }, []);

  // ── 即将过期定时器 ─────────────────────────────────────
  useEffect(() => {
    if (!user) {
      warningShownRef.current = false;
      return;
    }
    const token = localStorage.getItem("access_token");
    if (!token) return;
    const payload = safeDecodeJwt(token);
    if (!payload || payload.exp == null) return;

    const expiresAt = payload.exp * 1000;
    const warningAt = expiresAt - WARNING_BEFORE_SECONDS * 1000;
    const now = Date.now();

    // 已经过期了
    if (now >= expiresAt) {
      notifySessionExpired();
      return;
    }
    // 已经在预警窗口内
    if (now >= warningAt) {
      if (!warningShownRef.current) {
        warningShownRef.current = true;
        notifySessionWarning(Math.ceil((expiresAt - now) / 1000));
      }
      return;
    }
    // 还没到预警时间，设个定时器
    const delay = warningAt - now;
    const timer = setTimeout(() => {
      if (!warningShownRef.current) {
        warningShownRef.current = true;
        notifySessionWarning(WARNING_BEFORE_SECONDS);
      }
    }, delay);
    return () => clearTimeout(timer);
  }, [user]);

  // ── 监听全局会话事件 ───────────────────────────────────
  useEffect(() => {
    const onExpired = () => {
      setSessionDialog("expired");
    };
    const onWarning = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      const remaining = detail?.remainingSeconds ?? WARNING_BEFORE_SECONDS;
      setSessionRemainingSeconds(remaining);
      setSessionDialog((prev) => (prev === "expired" ? prev : "warning"));
    };

    window.addEventListener("session:expired", onExpired);
    window.addEventListener("session:warning", onWarning);
    return () => {
      window.removeEventListener("session:expired", onExpired);
      window.removeEventListener("session:warning", onWarning);
    };
  }, []);

  // ── 弹窗操作 ───────────────────────────────────────────
  const handleSessionGoLogin = useCallback(() => {
    clearSessionAndRedirect();
  }, []);

  const handleSessionExtend = useCallback(async () => {
    setSessionExtending(true);
    try {
      const ok = await refreshToken();
      if (ok) {
        warningShownRef.current = false;
        setSessionDialog(null);
      } else {
        setSessionDialog("expired");
      }
    } finally {
      setSessionExtending(false);
    }
  }, []);

  const handleSessionIgnore = useCallback(() => {
    setSessionDialog(null);
  }, []);

  // ── 登录 ───────────────────────────────────────────────
  const login = async (email: string, password: string) => {
    const data = await loginApi(email, password);
    const payload = safeDecodeJwt(data.access_token);
    if (!payload) {
      clearTokens();
      throw new Error("登录成功，但解析用户凭证失败，请重新登录");
    }
    setUser({
      id: Number(payload.sub),
      username: payload.username || "",
      email: payload.email || "",
    });
    warningShownRef.current = false; // 新登录重置预警标记
  };

  const register = async (
    username: string,
    email: string,
    password: string,
    password_confirm: string
  ) => {
    await registerApi(username, email, password, password_confirm);
  };

  const logout = async () => {
    await clearTokens();
    setUser(null);
    setSessionDialog(null);
    warningShownRef.current = false;
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        login,
        register,
        logout,
        sessionDialog,
        sessionRemainingSeconds,
        sessionExtending,
        handleSessionGoLogin,
        handleSessionExtend,
        handleSessionIgnore,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth 必须在 AuthProvider 内部使用");
  return ctx;
}
