import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children: ReactNode
  /** 局部边界（如消息列表）：兜底渲染为紧凑占位卡而非整页错误页，隔离故障区 */
  compact?: boolean
  /** 变化即重置错误态（数据换血后重新渲染 children） */
  resetKey?: string | null
}

interface State {
  error: Error | null
}

/** 渲染异常兜底（消灭白屏）：任何组件抛错时降级为可重载的错误页，错误详情可展开。
 *  compact=true 时降级为局部占位卡（根级整页兜底的下游还有一道），resetKey 变化
 *  （如切换数据集）自动重置重试。 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[ErrorBoundary]', error, info.componentStack)
  }

  componentDidUpdate(prev: Props) {
    if (this.state.error && prev.resetKey !== this.props.resetKey) {
      this.setState({ error: null })
    }
  }

  private renderDetails() {
    return (
      <details style={{ marginTop: 12, maxWidth: 640, fontSize: 12, opacity: 0.6 }}>
        <summary style={{ cursor: 'pointer' }}>错误详情</summary>
        <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
          {this.state.error!.stack ?? String(this.state.error)}
        </pre>
      </details>
    )
  }

  render() {
    if (!this.state.error) return this.props.children
    if (this.props.compact) {
      return (
        <div
          style={{
            margin: '12px auto',
            maxWidth: 720,
            width: '100%',
            display: 'flex',
            flexDirection: 'column',
            gap: 8,
            padding: 16,
            border: '1px solid var(--Color-border-default)',
            borderRadius: 8,
            background: 'var(--Color-bg-surface)',
            color: 'var(--Color-text-primary)',
            fontSize: 13,
          }}
        >
          <div style={{ fontSize: 14, fontWeight: 600 }}>部分消息渲染失败</div>
          <div style={{ opacity: 0.7 }}>这条消息的数据有问题，其他界面不受影响。</div>
          <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
            <button
              onClick={() => this.setState({ error: null })}
              style={{
                padding: '5px 14px',
                fontSize: 13,
                border: '1px solid var(--Color-border-default)',
                borderRadius: 8,
                background: 'var(--Color-bg-surface)',
                cursor: 'pointer',
              }}
            >
              重试渲染
            </button>
            <button
              onClick={() => window.location.reload()}
              style={{
                padding: '5px 14px',
                fontSize: 13,
                border: '1px solid var(--Color-border-default)',
                borderRadius: 8,
                background: 'var(--Color-bg-surface)',
                cursor: 'pointer',
              }}
            >
              重新加载
            </button>
          </div>
          {this.renderDetails()}
        </div>
      )
    }
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
          background: 'var(--Color-bg-canvas)',
          color: 'var(--Color-text-primary)',
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
            border: '1px solid var(--Color-border-default)',
            borderRadius: 8,
            background: 'var(--Color-bg-surface)',
            cursor: 'pointer',
          }}
        >
          重新加载
        </button>
        {this.renderDetails()}
      </div>
    )
  }
}
