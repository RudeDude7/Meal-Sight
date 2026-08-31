import path from 'node:path'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Backend target for the dev proxy — a real env var so a deployed
// build can point somewhere else without editing this file, but the
// proxy itself only ever runs during `vite dev`, never in a built
// bundle (see src/api/client.ts's own comment on VITE_API_BASE_URL).
const BACKEND_ORIGIN = process.env.VITE_BACKEND_ORIGIN ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    // Vite's own default (assets under 4KB get base64-inlined into the
    // JS bundle) would otherwise split RecipeIcon's own nine SVGs
    // arbitrarily — eight under the threshold, one (cow.svg, 4.5KB)
    // just over it — into two different loading strategies for what is
    // structurally the same kind of asset. Disabling inlining keeps all
    // nine as real, independently cacheable static files instead: the
    // icon set only needs to be downloaded once, ever, regardless of
    // how many recipe cards end up using it, rather than being
    // re-parsed as part of the JS bundle on every deploy that changes
    // unrelated code.
    assetsInlineLimit: 0,
  },
  server: {
    proxy: {
      '/api': {
        target: BACKEND_ORIGIN,
        changeOrigin: true,
      },
      '/health': {
        target: BACKEND_ORIGIN,
        changeOrigin: true,
      },
      '/ws': {
        target: BACKEND_ORIGIN,
        ws: true,
        changeOrigin: true,
      },
    },
  },
})
