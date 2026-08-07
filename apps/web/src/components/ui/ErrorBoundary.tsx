import { Component, type ErrorInfo, type ReactNode } from "react";

import { AlertTriangle, RefreshCw } from "lucide-react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

/** 错误边界：捕获子组件渲染异常，防止整页白屏。 */
export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  override componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("ErrorBoundary caught:", error, info.componentStack);
    // 动态 import 失败 = 新版本已部署、旧 chunk 已被 Service Worker 清理：
    // 自动刷新加载新 bundle，避免用户卡在错误页（仅触发一次）。
    if (
      error instanceof TypeError &&
      /Failed to fetch dynamically imported module/i.test(error.message)
    ) {
      if (!sessionStorage.getItem("eb-reload-once")) {
        sessionStorage.setItem("eb-reload-once", "1");
        window.location.reload();
      }
    }
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null });
  };

  override render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;
      return (
        <div className="flex flex-col items-center justify-center gap-4 py-24 text-center">
          <AlertTriangle className="h-10 w-10 text-danger" aria-hidden />
          <h2 className="text-lg font-semibold text-foreground">页面出了点问题</h2>
          <p className="max-w-sm text-sm text-muted-foreground">
            {this.state.error?.message || "渲染时发生未知错误"}
          </p>
          <button
            onClick={this.handleReset}
            className="inline-flex items-center gap-2 rounded-xl border border-border bg-surface px-4 py-2 text-sm font-medium hover:border-primary"
          >
            <RefreshCw className="h-4 w-4" aria-hidden />
            重试
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
