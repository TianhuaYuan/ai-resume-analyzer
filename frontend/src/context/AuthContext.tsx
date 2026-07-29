import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  type ReactNode,
} from "react";
import { login as loginApi, register as registerApi, logout as clearTokens, sendCode as sendCodeApi } from "../api/auth";
import { clearSessionAndRedirect } from "../api/client";
import { safeDecodeJwt } from "../utils/jwt";

interface User {
  id: number;
  username: string;
  email: string;
}

/** 会话弹窗类型：null=不弹、expired=已过期（refresh_token 也失效时） */
export type SessionDialogType = "expired" | null;

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
  /** 会话过期弹窗状态 */
  sessionDialog: SessionDialogType;
  /** 跳转登录页并清除 token */
  handleSessionGoLogin: () => void;
}

const AuthContext = createContext<AuthCtx | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  // 会话过期弹窗状态
  const [sessionDialog, setSessionDialog] = useState<SessionDialogType>(null);

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

  // ── 监听 session:expired 事件 ──────────────────────────
  // client.ts 中 401 → refresh 失败时触发
  useEffect(() => {
    const onExpired = () => {
      setSessionDialog("expired");
    };

    window.addEventListener("session:expired", onExpired);
    return () => {
      window.removeEventListener("session:expired", onExpired);
    };
  }, []);

  // ── 多 Tab 登出同步 ────────────────────────────────────
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key !== "access_token") return;
      if (!e.newValue) {
        setUser(null);
        setSessionDialog(null);
      }
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  // ── 弹窗操作 ───────────────────────────────────────────
  const handleSessionGoLogin = useCallback(() => {
    clearSessionAndRedirect();
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
        handleSessionGoLogin,
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
