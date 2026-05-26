import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/transcripts.json': 'http://localhost:5000',
      '/toggle-mute':      'http://localhost:5000',
      '/mute-status':      'http://localhost:5000',
      '/send-prompt':      'http://localhost:5000',
      '/events':           { target: 'http://localhost:5000', changeOrigin: true, ws: false },
    },
  },
  build: {
    outDir: '../static',
    emptyOutDir: true,
  },
})
