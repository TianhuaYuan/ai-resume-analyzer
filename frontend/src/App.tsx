import { BrowserRouter, Routes, Route, Navigate, useParams } from "react-router-dom";
import { useEffect, lazy, Suspense, type ReactNode } from "react";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { ThemeProvider } from "./context/ThemeContext";
import { WebSocketProvider } from "./context/WebSocketContext";
import AppLayout from "./AppLayout";
import ErrorBoundary from "./components/ErrorBoundary";
import { LoginModalHost, openLoginModal } from "./components/LoginModal";
import { ToastProvider, ToastContainer } from "./components/Toast";
import { captureCtaSource } from "./api/analytics";

// ── 路由级懒加载（拆分 JS bundle，首屏只加载当前路由代码） ──
const ForgotPasswordPage = lazy(() => import("./pages/ForgotPasswordPage"));
// C2: 信任合规公开页
const PrivacyPage = lazy(() => import("./pages/PrivacyPage"));
const TermsPage = lazy(() => import("./pages/TermsPage"));
const HomePage = lazy(() => import("./pages/HomePage"));
const QAPage = lazy(() => import("./pages/QAPage"));
const ResumeManagementPage = lazy(() => import("./pages/ResumeManagementPage"));
const BuilderPage = lazy(() =>
  import("./pages/BuilderPage").then((m) => ({ default: m.BuilderPage })),
);
const CampusPage = lazy(() => import("./pages/CampusPage"));
const CampusDetailPage = lazy(() => import("./pages/CampusDetailPage"));
const SocialPage = lazy(() => import("./pages/SocialPage"));
const FeedbackPage = lazy(() => import("./pages/FeedbackPage"));
const AdminPage = lazy(() => import("./pages/AdminPage"));

/** 懒加载路由的 fallback */
function PageLoader() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-[var(--color-bg)] text-[var(--color-text-secondary)] text-sm">
      <span className="inline-block w-5 h-5 rounded-full border-2 border-brand border-t-transparent animate-spin mr-2" />
      加载中...
    </div>
  );
}

/** 未登录占位（登录弹窗由 useEffect 触发，登录后自动恢复渲染 children） */
function LoginRequired() {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center gap-3 bg-[var(--color-bg)] text-[var(--color-text-secondary)] text-sm">
      <span>请先登录后访问</span>
      <button
        onClick={() => openLoginModal()}
        className="px-4 py-2 rounded-full bg-brand text-white text-sm font-semibold
          hover:bg-[#0077ed] hover:scale-[1.02] active:scale-[0.98]
          transition-all duration-300 cursor-pointer"
      >
        去登录
      </button>
    </div>
  );
}

function ProtectedRoute({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();

  // 未登录 → 自动弹出登录弹窗（登录成功后 user 更新，自动渲染 children）
  useEffect(() => {
    if (!loading && !user) openLoginModal();
  }, [loading, user]);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[var(--color-bg)] text-[var(--color-text-secondary)] text-sm">
        加载中...
      </div>
    );
  }

  if (!user) return <LoginRequired />;
  return <>{children}</>;
}

/** #9: 管理后台守卫 — 仅登录且 is_admin 可访问，否则跳回首页 */
function AdminRoute({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();

  // 未登录 → 自动弹出登录弹窗
  useEffect(() => {
    if (!loading && !user) openLoginModal();
  }, [loading, user]);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[var(--color-bg)] text-[var(--color-text-secondary)] text-sm">
        加载中...
      </div>
    );
  }

  if (!user) return <LoginRequired />;
  if (!user.is_admin) return <Navigate to="/" replace />;
  return <>{children}</>;
}

function AppRoutes() {
  return (
    <Suspense fallback={<PageLoader />}>
    <Routes>
      {/* 登录使用全局 LoginModal 弹窗，无独立 /login 页面 */}
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      {/* C2: 信任合规公开页（隐私政策 / 用户协议） */}
      <Route path="/privacy" element={<PrivacyPage />} />
      <Route path="/terms" element={<TermsPage />} />
      {/* 首页：登录/未登录两种视图，无侧边栏 */}
      <Route path="/" element={<HomePage />} />
      {/* Agent 聊天页（侧边栏布局） */}
      <Route
        path="/qa"
        element={
          <ProtectedRoute>
            <AppLayout>
              <QAPage />
            </AppLayout>
          </ProtectedRoute>
        }
      />
      {/* 简历管理页 */}
      <Route
        path="/resumes"
        element={
          <ProtectedRoute>
            <AppLayout>
              <ResumeManagementPage />
            </AppLayout>
          </ProtectedRoute>
        }
      />
      {/* 简历编辑器 */}
      <Route
        path="/resumes/:id/edit"
        element={
          <ProtectedRoute>
            <AppLayout>
              <BuilderPageRouteWrapper />
            </AppLayout>
          </ProtectedRoute>
        }
      />
      {/* 兼容旧路由 /resumes/:id → 重定向到编辑器 */}
      <Route path="/resumes/:id" element={<ResumeRedirect />} />
      {/* 校招页（公开，未登录可浏览） */}
      <Route
        path="/campus"
        element={
          <AppLayout>
            <CampusPage />
          </AppLayout>
        }
      />
      {/* 校招详情页（公开，站内阅读） */}
      <Route path="/campus/:id" element={<CampusDetailPage />} />
      {/* 社招页（公开，未登录可浏览） */}
      <Route
        path="/social"
        element={
          <AppLayout>
            <SocialPage />
          </AppLayout>
        }
      />
      {/* 用户反馈页（公开） */}
      <Route
        path="/feedback"
        element={
          <AppLayout>
            <FeedbackPage />
          </AppLayout>
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

/** 从路由参数提取 resumeId 传给 BuilderPage */
function BuilderPageRouteWrapper() {
  const params = useParams<{ id: string }>();
  const resumeId = Number(params.id);
  if (!resumeId || isNaN(resumeId)) {
    return (
      <div className="flex-1 flex items-center justify-center text-[var(--color-text-muted)] text-sm">
        无效的简历 ID
      </div>
    );
  }
  return <BuilderPage resumeId={resumeId} />;
}

/** 兼容旧路由 /resumes/:id → 重定向到编辑器（动态参数） */
function ResumeRedirect() {
  const { id } = useParams<{ id: string }>();
  return <Navigate to={`/resumes/${id}/edit`} replace />;
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
                <LoginModalHost />
                <ToastContainer />
              </WebSocketProvider>
            </ToastProvider>
          </AuthProvider>
        </BrowserRouter>
      </ThemeProvider>
    </ErrorBoundary>
  );
}
