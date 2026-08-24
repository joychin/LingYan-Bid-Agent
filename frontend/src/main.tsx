import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import './index.css'
import './styles/workspace.css'
import App from './App.tsx'
import { ToastProvider } from './context/Toast'
import { SidecarHealthProvider } from './context/SidecarHealth'
import { FileUploadProvider } from './context/FileUpload'

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
