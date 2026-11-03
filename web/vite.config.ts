import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
// 开发态：把 /api 转发到业务后端（FastAPI，默认 127.0.0.1:8011）。
// 前端各页面直接 fetch('/api/...')，无需改调用点；生产用同源反向代理。
const BACKEND = process.env.VITE_BACKEND_URL ?? 'http://127.0.0.1:8011'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: true,
    proxy: {
      '/api': {
        target: BACKEND,
        changeOrigin: true,
      },
    },
  },
  preview: {
    proxy: {
      '/api': {
        target: BACKEND,
        changeOrigin: true,
      },
    },
  },
})
