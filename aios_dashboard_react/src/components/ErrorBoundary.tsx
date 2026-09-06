import React from 'react';

// Minimal ErrorBoundary — catches render throws so one bad card doesn't blank the whole dashboard.
// ponytail: upgrade to per-route boundaries + Sentry when we need finer isolation.
export class ErrorBoundary extends React.Component<
  { children: React.ReactNode; fallback?: React.ReactNode },
  { hasError: boolean; error: Error | null }
> {
  state = { hasError: false, error: null as Error | null };
  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error };
  }
  componentDidCatch(error: Error) {
    // Visible in dev console; no external reporting yet.
    console.error('[ErrorBoundary]', error);
  }
  render() {
    if (this.state.hasError) {
      return (
        this.props.fallback ?? (
          <div className="alert alert-danger m-4" role="alert">
            <strong>Terjadi kesalahan render.</strong>
            <div className="mt-1 mono" style={{ fontSize: 12, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
              {this.state.error?.message ?? 'Unknown error'}
            </div>
            <button className="btn btn-sm btn-outline-secondary mt-2" onClick={() => this.setState({ hasError: false, error: null })}>
              Coba lagi
            </button>
          </div>
        )
      );
    }
    return this.props.children;
  }
}
