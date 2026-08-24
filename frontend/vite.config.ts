import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': new URL('./src', import.meta.url).pathname,
    },
  },
  server: {
    // 固定端口：端口被占时宁可启动失败也不悄悄回退——回退会让 CORS 白名单失效，
    // 浏览器模式下所有 /api 请求静默失败。
    port: 5173,
    strictPort: true,
    proxy: {
      // 浏览器开发模式同源转发到 sidecar（`npm run dev:browser` 固定起在 8765）。
      // 前端走相对路径 /api/... 即由 Vite 转发，彻底规避 CORS；SSE 长连接也能透传。
      // 需要直连（绕过 proxy）时用 VITE_SIDECAR_URL 覆盖。
      '/api': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: true,
      },
    },
  },
})
