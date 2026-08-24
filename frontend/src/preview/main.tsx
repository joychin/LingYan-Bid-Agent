import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import '@/styles/workspace.css'
import { PreviewPage } from './PreviewPage'

// 预览页独立入口：只引 workspace.css，不依赖 index.css / Tailwind / 后端
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <PreviewPage />
  </StrictMode>,
)
