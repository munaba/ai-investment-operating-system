import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev proxy: the ASP.NET minimal-API host (http://localhost:5000) exposes
// /api, /login, /logout. Proxying them through Vite's origin means the auth
// cookie is first-party, so credentials:'include' works in development.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://localhost:5000', changeOrigin: true },
      '/login': { target: 'http://localhost:5000', changeOrigin: true },
      '/logout': { target: 'http://localhost:5000', changeOrigin: true },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    css: false,
  },
})
