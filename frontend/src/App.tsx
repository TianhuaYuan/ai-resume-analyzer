import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { useEffect, lazy, Suspense, type ReactNode } from "react";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { ThemeProvider } from "./context/ThemeContext";
import { WebSocketProvider } from "./context/WebSocketContext";
import AppLayout from "./AppLayout";
import ErrorBoundary from "./components/ErrorBoundary";
import { ToastProvider, ToastContainer } from "./components/Toast";
import { captureCtaSource } from "./api/analytics";

// ── 路由级懒加载（拆分 JS bundle，首屏只加载当前路由代码） ──
const LoginPage = lazy(() => import("./pages/LoginPage"));
const ForgotPasswordPage = lazy(() => import("./pages/ForgotPasswordPage"));
const HomePage = lazy(() => import("./pages/HomePage"));
const AdminPage = lazy(() => import("./pages/AdminPage"));
const WorkbenchPage = lazy(() => import("./pages/WorkbenchPage"));

/** 懒加载路由的 fallback */
function PageLoader() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-[var(--color-bg)] text-[var(--color-text-secondary)] text-sm">
      <span className="inline-block w-5 h-5 rounded-full border-2 border-indigo-400 border-t-transparent animate-spin mr-2" />
      加载中...
    </div>
  );
}

function ProtectedRoute({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[var(--color-bg)] text-[var(--color-text-secondary)] text-sm">
        加载中...
      </div>
    );
  }

  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

/** #9: 管理后台守卫 — 仅登录且 is_admin 可访问，否则跳回首页 */
function AdminRoute({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[var(--color-bg)] text-[var(--color-text-secondary)] text-sm">
        加载中...
      </div>
    );
  }

  if (!user) return <Navigate to="/login" replace />;
  if (!user.is_admin) return <Navigate to="/" replace />;
  return <>{children}</>;
}

function AppRoutes() {
  return (
    <Suspense fallback={<PageLoader />}>
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <AppLayout>
              <HomePage />
            </AppLayout>
          </ProtectedRoute>
        }
      />
      <Route
        path="/resumes/:id"
        element={
          <ProtectedRoute>
            {/* T20: showSidebar=true → Sidebar + Tab(聊天|编辑) + QAPage */}
            <AppLayout showSidebar />
          </ProtectedRoute>
        }
      />
      <Route
        path="/workbench"
        element={
          <ProtectedRoute>
            <AppLayout>
              <WorkbenchPage />
            </AppLayout>
          </ProtectedRoute>
        }
      />
      <Route
        path="/admin"
        element={
          <AdminRoute>
            <AppLayout>
              <AdminPage />
            </AppLayout>
          </AdminRoute>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
    </Suspense>
  );
}

export default function App() {
  // T37: 应用挂载时捕获 URL 中的 ?source= 参数（CTA 渠道），存入 localStorage
  useEffect(() => {
    captureCtaSource();
  }, []);

  return (
    <ErrorBoundary>
      <ThemeProvider>
        <BrowserRouter>
          <AuthProvider>
            <ToastProvider>
              <WebSocketProvider>
                <AppRoutes />
                <ToastContainer />
              </WebSocketProvider>
            </ToastProvider>
          </AuthProvider>
        </BrowserRouter>
      </ThemeProvider>
    </ErrorBoundary>
  );
}
