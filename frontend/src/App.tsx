import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "./context/AuthContext";
import type { ReactNode } from "react";
import Navbar from "./components/Navbar";
import ErrorBoundary from "./components/ErrorBoundary";
import SessionExpiredDialog from "./components/SessionExpiredDialog";
import { ToastProvider, ToastContainer } from "./components/Toast";
import LoginPage from "./pages/LoginPage";
import ResumeListPage from "./pages/ResumeListPage";
import QAPage from "./pages/QAPage";

function ProtectedRoute({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#0f172a] text-slate-400 text-sm">
        加载中...
      </div>
    );
  }

  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function AppLayout({ children }: { children: ReactNode }) {
  const {
    sessionDialog,
    sessionRemainingSeconds,
    sessionExtending,
    handleSessionGoLogin,
    handleSessionExtend,
    handleSessionIgnore,
  } = useAuth();

  return (
    <>
      <Navbar />
      {children}
      <SessionExpiredDialog
        open={sessionDialog !== null}
        mode={sessionDialog ?? "expired"}
        remainingSeconds={sessionRemainingSeconds}
        loading={sessionExtending}
        onPrimary={
          sessionDialog === "warning" ? handleSessionExtend : handleSessionGoLogin
        }
        onIgnore={handleSessionIgnore}
      />
    </>
  );
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <AppLayout>
              <ResumeListPage />
            </AppLayout>
          </ProtectedRoute>
        }
      />
      <Route
        path="/resumes/:id"
        element={
          <ProtectedRoute>
            <AppLayout>
              <QAPage />
            </AppLayout>
          </ProtectedRoute>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <AuthProvider>
          <ToastProvider>
            <AppRoutes />
            <ToastContainer />
          </ToastProvider>
        </AuthProvider>
      </BrowserRouter>
    </ErrorBoundary>
  );
}
