import { Component, type ReactNode, type ErrorInfo } from "react";
import { AlertTriangle } from "lucide-react";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("ErrorBoundary caught:", error, info);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen flex items-center justify-center bg-surface2">
          <div className="card max-w-md text-center">
            <AlertTriangle className="w-12 h-12 text-warn mx-auto mb-4" />
            <h2 className="text-xl font-bold text-ink mb-2">
              Algo sali&oacute; mal
            </h2>
            <p className="text-muted mb-4 text-sm">
              {this.state.error?.message}
            </p>
            <button
              onClick={() => window.location.reload()}
              className="btn-primary"
            >
              Recargar
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
