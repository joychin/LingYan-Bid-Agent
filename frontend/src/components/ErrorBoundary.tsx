import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children: ReactNode
}

interface State {
  error: Error | null
}

/** 渲染异常兜底（消灭白屏）：任何组件抛错时降级为可重载的错误页，错误详情可展开。 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[ErrorBoundary]', error, info.componentStack)
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div
        style={{
          minHeight: '100vh',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 12,
          padding: 24,
          background: 'var(--paper, #fafaf9)',
          color: 'var(--ink, #1c1917)',
          fontFamily: 'inherit',
        }}
      >
        <div style={{ fontSize: 15, fontWeight: 600 }}>页面渲染出错了</div>
        <div style={{ fontSize: 13, opacity: 0.7 }}>界面遇到意外错误，重新加载通常可以恢复。</div>
        <button
          onClick={() => window.location.reload()}
          style={{
            marginTop: 8,
            padding: '6px 16px',
            fontSize: 13,
            border: '1px solid var(--line, #e7e5e4)',
            borderRadius: 8,
            background: 'var(--panel, #ffffff)',
            cursor: 'pointer',
          }}
        >
          重新加载
        </button>
        <details style={{ marginTop: 12, maxWidth: 640, fontSize: 12, opacity: 0.6 }}>
          <summary style={{ cursor: 'pointer' }}>错误详情</summary>
          <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
            {this.state.error.stack ?? String(this.state.error)}
          </pre>
        </details>
      </div>
    )
  }
}
