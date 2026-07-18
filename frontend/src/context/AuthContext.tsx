import {
  createContext,
  useContext,
  useState,
  useEffect,
  type ReactNode,
} from "react";
import { login as loginApi, register as registerApi, logout as clearTokens } from "../api/auth";
import { safeDecodeJwt } from "../utils/jwt";

interface User {
  id: number;
  username: string;
  email: string;
}

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
  logout: () => void;
}

const AuthContext = createContext<AuthCtx | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  // 启动时从 token 里解码 user 信息（不做 API 请求，减少等待）
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

  const login = async (email: string, password: string) => {
    const data = await loginApi(email, password);
    // 解码 token 拿到 user 信息（H9：即便 token 异常也不崩，回退为未登录）
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
    password_confirm: string
  ) => {
    await registerApi(username, email, password, password_confirm);
  };

  const logout = () => {
    clearTokens();
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth 必须在 AuthProvider 内部使用");
  return ctx;
}
