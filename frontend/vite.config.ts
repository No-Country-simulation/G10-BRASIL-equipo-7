import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { loadEnv } from 'vite'
import { defineConfig } from 'vitest/config'
import { readFileSync } from 'node:fs'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'API_PROXY_')
  const limites = JSON.parse(readFileSync(new URL('../config/chat.json', import.meta.url), 'utf8'))

  return {
    plugins: [react(), tailwindcss()],
    define: { __CHAT_LIMITS__: JSON.stringify({ maxAnexoMb: limites.max_anexo_mb, maxMensagens: limites.max_interacoes_historico }) },
    server: {
      host: '127.0.0.1',
      port: 5173,
      strictPort: true,
      proxy: {
        '^/api(?:/|$)': {
          target: env.API_PROXY_TARGET || 'http://127.0.0.1:8000',
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api(?=\/|$)/, '') || '/',
        },
      },
    },
    test: {
      environment: 'jsdom',
      setupFiles: ['./src/test/setup.ts'],
    },
  }
})
