import { Component } from 'react'
import type { ErrorInfo, ReactNode } from 'react'

interface ErrorBoundaryProps {
  children: ReactNode
}

interface ErrorBoundaryState {
  error: Error | null
}

/**
 * React only supports catching render-time errors via a class
 * component's own componentDidCatch — there is no hook equivalent as
 * of React 18, so this one piece of the app is deliberately not a
 * function component.
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error }
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    // eslint-disable-next-line no-console
    console.error('Unhandled error in component tree:', error, info.componentStack)
  }

  private handleReset = (): void => {
    this.setState({ error: null })
  }

  override render(): ReactNode {
    if (this.state.error) {
      return (
        <div className="mx-auto max-w-lg rounded-card border border-danger-500/20 bg-danger-50 p-6 text-center">
          <p className="text-subtitle text-danger-600">Something went wrong.</p>
          <p className="mt-2 text-body text-ink-muted">{this.state.error.message}</p>
          <button
            type="button"
            onClick={this.handleReset}
            className="mt-4 rounded-card bg-brand-600 px-4 py-2 text-body font-medium text-white hover:bg-brand-700"
          >
            Try again
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
