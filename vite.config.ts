import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// base: './' → 相对资源路径，GitHub Pages 项目站点也能直接跑
export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: './',
})
