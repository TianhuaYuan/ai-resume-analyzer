import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  useRef,
  type ReactNode,
} from "react";
import { login as loginApi, register as registerApi, logout as clearTokens, sendCode as sendCodeApi } from "../api/auth";
import { refreshToken, clearSessionAndRedirect, notifySessionExpired, notifySessionWarning } from "../api/client";
import { safeDecodeJwt } from "../utils/jwt";
import { computeSessionWarning } from "./sessionWarning";

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
    password_confirm: string,
    verification_code: string
  ) => Promise<void>;
  sendCode: (email: string) => Promise<string>;
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
  // P1-19：token 版本号，续期成功后递增，触发预警定时器重新调度
  const [tokenVersion, setTokenVersion] = useState(0);

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
  // P1-19：依赖 tokenVersion，续期成功后递增它，触发定时器基于新 token 重新调度
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
    const now = Date.now();
    const decision = computeSessionWarning(expiresAt, now, WARNING_BEFORE_SECONDS);

    if (decision.kind === "expired") {
      notifySessionExpired();
      return;
    }
    if (decision.kind === "warning") {
      if (!warningShownRef.current) {
        warningShownRef.current = true;
        notifySessionWarning(decision.remainingSeconds);
      }
      return;
    }
    // schedule
    const timer = setTimeout(() => {
      if (!warningShownRef.current) {
        warningShownRef.current = true;
        notifySessionWarning(WARNING_BEFORE_SECONDS);
      }
    }, decision.delayMs);
    return () => clearTimeout(timer);
  }, [user, tokenVersion]);

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

  // ── P2-17：多 Tab 登出同步 ──────────────────────────────
  // storage 事件只在「其他 Tab/Window」修改 localStorage 时触发，当前 Tab 不会收到。
  // 当其他 Tab 登出（移除 access_token 或替换为无效值）时，当前 Tab 同步登出。
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key !== "access_token") return;
      // newValue 为 null（移除）或空串（替换为无效值）→ 同步登出
      if (!e.newValue) {
        setUser(null);
        setSessionDialog(null);
        warningShownRef.current = false;
      }
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
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
        // P1-19：递增 tokenVersion，触发预警定时器基于新 token 的 exp 重新调度
        setTokenVersion((v) => v + 1);
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
    setTokenVersion((v) => v + 1); // P1-19：新 token 触发定时器调度
  };

  const register = async (
    username: string,
    email: string,
    password: string,
    password_confirm: string,
    verification_code: string
  ) => {
    await registerApi(username, email, password, password_confirm, verification_code);
  };

  const sendCode = async (email: string) => {
    return await sendCodeApi(email);
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
        sendCode,
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
