import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', 'SPATIAL_')
  const target = env.SPATIAL_API_URL || 'http://127.0.0.1:8000'
  const proxy = Object.fromEntries(
    ['/api', '/docs', '/openapi.json'].map((path) => [path, { target, changeOrigin: true }]),
  )
  return {
    plugins: [react()],
    server: { proxy },
    preview: { proxy },
    build: {
      manifest: true,
      rollupOptions: {
        output: {
          manualChunks(id) {
            if (id.replaceAll('\\', '/').includes('/node_modules/three/')) return 'three'
          },
        },
      },
    },
  }
})
