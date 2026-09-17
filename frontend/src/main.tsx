import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import './index.css'
import './styles/workspace.css'
import App from './App.tsx'
import { ToastProvider } from './context/Toast'
import { SidecarHealthProvider } from './context/SidecarHealth'
import { FileUploadProvider } from './context/FileUpload'

// macOS Tauri 才有红绿灯悬浮（Overlay 标题栏）：挂类驱动让位 CSS；
// 浏览器模式与 Windows 不挂，布局零变化
if ('__TAURI_INTERNALS__' in window && /Mac/i.test(navigator.userAgent)) {
  document.documentElement.classList.add('mac-tauri')
}

// 主题首帧落位（防闪白）：localStorage 记忆优先，否则跟随系统；
// 值与 styles/tokens.css 的 [data-theme="dark"] 选择器约定对齐
const LS_THEME = 'tender-agent.theme'
const storedTheme = localStorage.getItem(LS_THEME)
document.documentElement.dataset.theme =
  storedTheme === 'dark' || storedTheme === 'light'
    ? storedTheme
    : window.matchMedia('(prefers-color-scheme: dark)').matches
      ? 'dark'
      : 'light'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      staleTime: 1000,
      // 全局快速失败（2026-09-17 批次⑤）：默认 retry 3 × 15s 请求超时 ≈ 67s 骨架屏
      // 才进错误态（useMessages 先例注释同口径）；sidecar 重启是高频场景，1 次重试
      // ≈ 31s 内给出可见可重试的错误卡。个别查询仍可自行覆写
      retry: 1,
    },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <SidecarHealthProvider>
          <FileUploadProvider>
            <App />
          </FileUploadProvider>
        </SidecarHealthProvider>
      </ToastProvider>
    </QueryClientProvider>
  </StrictMode>,
)
