import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// 开发期通过代理保持前后端同源，避免 CORS 与 Cookie 域问题（PRD 15.10）
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: false,
        ws: true,
      },
    },
  },
})
