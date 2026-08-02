import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  useMemo,
  type ReactNode,
} from "react";
import { login as loginApi, register as registerApi, logout as clearTokens, sendCode as sendCodeApi, getCurrentUser } from "../api/auth";
import { clearSessionAndRedirect } from "../api/client";
import { safeDecodeJwt } from "../utils/jwt";

interface User {
  id: number;
  username: string;
  email: string;
  /** #9: 是否管理员（控制管理后台入口可见性） */
  is_admin?: boolean;
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
  /** 更新本地用户信息（修改用户名/邮箱后同步） */
  updateUser: (patch: Partial<Pick<User, "username" | "email">>) => void;
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

  // ── 启动时从 /me 获取完整用户信息 ──────────────────────
  // 性能优化：token 有效时先用 JWT 里的信息立即渲染（消除白屏等待），
  // /me 在后台刷新为完整信息（is_admin 等字段 /me 后修正）。
  useEffect(() => {
    const token = localStorage.getItem("access_token");
    if (!token) {
      setLoading(false);
      return;
    }
    const payload = safeDecodeJwt(token);
    if (!payload || payload.exp == null || payload.exp * 1000 <= Date.now()) {
      clearTokens();
      setLoading(false);
      return;
    }
    // 先用 JWT 预填充，立即放行渲染
    setUser({
      id: Number(payload.sub) || 0,
      username: payload.username ?? "",
      email: payload.email ?? "",
      is_admin: false, // 以 /me 返回为准，稍后修正
    });
    setLoading(false);
    // 后台刷新完整用户信息（含 is_admin / 最新用户名邮箱）
    getCurrentUser()
      .then((data) => {
        setUser({
          id: data.id,
          username: data.username,
          email: data.email,
          is_admin: data.is_admin ?? false,
        });
      })
      .catch(() => {
        // /me 失败（token 被撤销等）→ 清 token 并登出
        clearTokens();
        setUser(null);
      });
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
  const login = useCallback(async (email: string, password: string) => {
    await loginApi(email, password);
    const userInfo = await getCurrentUser();
    setUser({
      id: userInfo.id,
      username: userInfo.username,
      email: userInfo.email,
      is_admin: userInfo.is_admin ?? false,
    });
  }, []);

  const register = useCallback(async (
    username: string,
    email: string,
    password: string,
    password_confirm: string,
    verification_code: string
  ) => {
    await registerApi(username, email, password, password_confirm, verification_code);
  }, []);

  const sendCode = useCallback(async (email: string) => {
    return await sendCodeApi(email);
  }, []);

  const logout = useCallback(async () => {
    await clearTokens();
    setUser(null);
    setSessionDialog(null);
  }, []);

  const updateUser = useCallback((patch: Partial<Pick<User, "username" | "email">>) => {
    setUser((prev) => (prev ? { ...prev, ...patch } : prev));
  }, []);

  // ── memoize context value，避免每次 AuthProvider 渲染时创建新对象 → 所有消费者重渲染 ──
  const value = useMemo<AuthCtx>(
    () => ({
      user,
      loading,
      login,
      register,
      sendCode,
      logout,
      updateUser,
      sessionDialog,
      handleSessionGoLogin,
    }),
    [user, loading, login, register, sendCode, logout, updateUser, sessionDialog, handleSessionGoLogin]
  );

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth 必须在 AuthProvider 内部使用");
  return ctx;
}
