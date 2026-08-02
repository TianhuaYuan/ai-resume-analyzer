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
const QAPage = lazy(() => import("./pages/QAPage"));
const ResumeManagementPage = lazy(() => import("./pages/ResumeManagementPage"));
const BuilderPage = lazy(() =>
  import("./pages/BuilderPage").then((m) => ({ default: m.BuilderPage })),
);
const CampusPage = lazy(() => import("./pages/CampusPage"));
const CampusDetailPage = lazy(() => import("./pages/CampusDetailPage"));
const SocialPage = lazy(() => import("./pages/SocialPage"));
const TemplatesPage = lazy(() => import("./pages/TemplatesPage"));
const TemplateDetailPage = lazy(() => import("./pages/TemplateDetailPage"));
const ExamplesPage = lazy(() => import("./pages/ExamplesPage"));
const ExampleDetailPage = lazy(() => import("./pages/ExampleDetailPage"));
const TipsPage = lazy(() => import("./pages/TipsPage"));
const GuideDetailPage = lazy(() => import("./pages/GuideDetailPage"));
const FeedbackPage = lazy(() => import("./pages/FeedbackPage"));
const ProductUpdatesPage = lazy(() => import("./pages/ProductUpdatesPage"));
const AdminPage = lazy(() => import("./pages/AdminPage"));
const WorkbenchPage = lazy(() => import("./pages/WorkbenchPage"));

/** 懒加载路由的 fallback */
function PageLoader() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-[var(--color-bg)] text-[var(--color-text-secondary)] text-sm">
      <span className="inline-block w-5 h-5 rounded-full border-2 border-brand border-t-transparent animate-spin mr-2" />
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
      <Route path="/resumes/:id" element={<Navigate to="/resumes/:id/edit" replace />} />
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
      {/* 简历模板详情页（公开） */}
      <Route path="/templates/:id" element={<TemplateDetailPage />} />
      {/* 简历模板页（公开） */}
      <Route path="/templates" element={<TemplatesPage />} />
      {/* 简历范文页（公开） */}
      <Route path="/examples" element={<ExamplesPage />} />
      {/* 简历范文详情页（公开） */}
      <Route path="/examples/:id" element={<ExampleDetailPage />} />
      {/* 求职攻略页（公开） */}
      <Route path="/tips" element={<TipsPage />} />
      {/* 攻略详情页（公开，站内阅读） */}
      <Route
        path="/guides/:id"
        element={
          <AppLayout>
            <GuideDetailPage />
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
      {/* 产品更新页（公开） */}
      <Route
        path="/product-updates"
        element={
          <AppLayout>
            <ProductUpdatesPage />
          </AppLayout>
        }
      />
      {/* 求职看板页（公开） */}
      <Route
        path="/workbench"
        element={
          <AppLayout>
            <WorkbenchPage />
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

import { useParams } from "react-router-dom";

export default function App() {
  // T37: 应用挂载时捕获 URL 中的 ?source= 参数（CTA 渠道），存入 localStorage
  useEffect(() => {
    captureCtaSource();
  }, []);

  return (
    <ErrorBoundary>
      <ThemeProvider>
        <BrowserRouter>
        <ThemeProvider>
          <AuthProvider>
            <ToastProvider>
              <WebSocketProvider>
                <AppRoutes />
                <ToastContainer />
              </WebSocketProvider>
            </ToastProvider>
          </AuthProvider>
        </ThemeProvider>
      </BrowserRouter>
      </ThemeProvider>
    </ErrorBoundary>
  );
}
