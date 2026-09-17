import { createRequire } from 'node:module'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// 根 tsconfig 是 NodeNext：JSON import 需要属性语法，vite 对此有兼容坑，改走 require
const require = createRequire(import.meta.url)
// 版本号唯一真源 = src-tauri/tauri.conf.json（CI 出包时经 scripts/set_version.py
// 从 tag 同步写全部五处）。前端 package.json 的 version 是五处之一（历史注记：
// 2026-09-15 前它恒为 0.0.0 且被当显示真源，导致设置页显示错版号——修复后只认
// tauri.conf.json）。
const tauriConf = require('../src-tauri/tauri.conf.json') as { version: string }

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  // __APP_VERSION__：应用版本号（src/env.d.ts 有声明；设置窗「通用」页展示 + 版本检查比较）
  define: {
    __APP_VERSION__: JSON.stringify(tauriConf.version),
  },
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
