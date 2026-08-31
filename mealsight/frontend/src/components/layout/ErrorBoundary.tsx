import { Component } from 'react'
import type { ErrorInfo, ReactNode } from 'react'

import { Button } from '@/components/primitives/Button'
import { Stamp } from '@/components/primitives/Stamp'

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
      // NEGATIVE state pattern: a signal-negative Stamp, a plain-
      // language explanation, and always a concrete next action — the
      // same vocabulary as a considered "no cookable recipe" result,
      // because both are real negative outcomes; what differs is only
      // the explanation text, not the pattern itself.
      return (
        <div className="mx-auto max-w-lg rounded-sm border border-signal-negative/20 bg-signal-negative/10 p-6 text-center">
          <Stamp signal="negative">error</Stamp>
          <p className="mt-2 text-heading text-signal-negative">Something went wrong.</p>
          <p className="mt-2 text-body-lg text-ink-600">{this.state.error.message}</p>
          <Button variant="primary" onClick={this.handleReset} className="mt-4">
            Try again
          </Button>
        </div>
      )
    }
    return this.props.children
  }
}
