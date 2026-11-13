import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const hermes3dTarget = 'http://127.0.0.1:3000'

const hermes3dProxy = {
  target: hermes3dTarget,
  changeOrigin: true,
  ws: true,
}

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      // Serve Hermes3D through AgentHQ's own origin. This allows its existing
      // SAMEORIGIN / frame-ancestors CSP headers to remain enabled.
      '/office': { ...hermes3dProxy },
      '/_next': { ...hermes3dProxy },
      '/api': { ...hermes3dProxy },
      '/office-assets': { ...hermes3dProxy },
      '/spotify': { ...hermes3dProxy },
    },
  },
})
