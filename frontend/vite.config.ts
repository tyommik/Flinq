import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type AnyConfig = any

const API_TARGET = process.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    host: true,
    proxy: {
      '/health': { target: API_TARGET, changeOrigin: true },
      '/auth': { target: API_TARGET, changeOrigin: true },
      '/me': { target: API_TARGET, changeOrigin: true },
      '/lessons': { target: API_TARGET, changeOrigin: true },
      '/reader': { target: API_TARGET, changeOrigin: true },
      '/vocabulary': { target: API_TARGET, changeOrigin: true },
      '/dictionary': { target: API_TARGET, changeOrigin: true },
      '/review': { target: API_TARGET, changeOrigin: true },
      '/stats': { target: API_TARGET, changeOrigin: true },
      '/admin': { target: API_TARGET, changeOrigin: true },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./tests/setup.ts'],
    css: false,
  },
} as AnyConfig)
