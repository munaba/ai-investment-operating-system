import path from 'path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev proxy: the ASP.NET minimal-API host (http://localhost:5000) exposes
// /api, /login, /logout. Proxying them through Vite's origin means the auth
// cookie is first-party, so credentials:'include' works in development.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://localhost:5000', changeOrigin: true },
      // NOTE: do NOT proxy '/login' — the React SPA owns the /login route
      // (src/pages/Login.tsx). Proxying it handed the request to the ASP.NET
      // host, which served its Blazor login page instead of the React app.
      // Frontend auth uses POST /api/auth/login (under /api) + GET /logout.
      '/logout': { target: 'http://localhost:5000', changeOrigin: true },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    css: false,
    exclude: ['**/node_modules/**', '**/e2e/**'],
  },
})
