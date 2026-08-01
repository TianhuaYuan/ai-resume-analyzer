import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8081',
        changeOrigin: true,
      },
    },
  },
  build: {
    rollupOptions: {
      output: {
        // Vite v8 (rolldown) 要求 manualChunks 为函数
        manualChunks(id) {
          if (!id.includes('node_modules')) return;
          const p = id.replace(/\\/g, '/');

          if (p.includes('@phosphor-icons')) return 'icons';
          if (p.includes('recharts')) return 'charts';
          if (p.includes('framer-motion')) return 'animation';
          if (
            p.includes('react-markdown') ||
            p.includes('remark-') ||
            p.includes('rehype-')
          )
            return 'markdown';
          if (
            p.includes('/react-dom') ||
            p.includes('/react-router') ||
            p.includes('/react/')
          )
            return 'react-vendor';
        },
      },
    },
  },
})
