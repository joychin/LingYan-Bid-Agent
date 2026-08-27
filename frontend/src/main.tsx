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

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      staleTime: 1000,
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
