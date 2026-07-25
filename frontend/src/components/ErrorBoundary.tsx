import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

/**
 * React 错误边界：捕获子组件渲染错误，展示友好错误 UI + 重试按钮。
 * 用法：<ErrorBoundary><YourComponent /></ErrorBoundary>
 */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[ErrorBoundary]", error, info.componentStack);
  }

  private handleRetry = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;

      return (
        <div className="min-h-screen flex items-center justify-center bg-[var(--color-bg)] px-4">
          <div className="max-w-md w-full bg-[var(--color-surface)] rounded-xl p-8 text-center shadow-lg">
            <div className="text-5xl mb-4">💥</div>
            <h2 className="text-xl font-semibold text-[var(--color-text)] mb-2">
              页面出错了
            </h2>
            <p className="text-[var(--color-text-secondary)] text-sm mb-6 break-all">
              {this.state.error?.message || "发生了未知错误"}
            </p>
            <button
              onClick={this.handleRetry}
              className="px-6 py-2.5 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-sm font-medium transition-colors"
            >
              重试
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
