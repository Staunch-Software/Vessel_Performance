import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
// MapLibre GL is loaded via CDN in index.html to avoid Vite worker minification
// bugs that cause "wm is not defined" in production builds.
export default defineConfig({
  plugins: [react()],
  build: {
    target: 'esnext',
  }
})
