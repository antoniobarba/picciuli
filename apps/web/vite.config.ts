/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react';
import { defineConfig, loadEnv } from 'vite';
import { VitePWA } from 'vite-plugin-pwa';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  // In development the API is reached through this proxy, so its CORS
  // settings do not need to list the local origin.
  const apiTarget = env.PICCIULI_API_PROXY || 'https://api.picciuli.party';

  return {
    plugins: [
      react(),
      VitePWA({
        registerType: 'prompt',
        injectRegister: false,
        pwaAssets: { config: true, overrideManifestIcons: true },
        manifest: {
          name: 'Picciuli',
          short_name: 'Picciuli',
          description: 'Personal budgeting and money tracking',
          lang: 'en',
          start_url: '/',
          scope: '/',
          display: 'standalone',
          orientation: 'any',
          background_color: '#f6f7f9',
          theme_color: '#0f7b63',
          categories: ['finance', 'productivity'],
        },
        workbox: {
          globPatterns: ['**/*.{js,css,html,svg,png,ico,woff2}'],
          navigateFallback: '/index.html',
          navigateFallbackDenylist: [/^\/config\.json$/, /^\/api\//],
          cleanupOutdatedCaches: true,
        },
      }),
    ],
    server: {
      port: 5173,
      strictPort: true,
      proxy: {
        '/api': { target: apiTarget, changeOrigin: true, secure: true },
        '/healthz': { target: apiTarget, changeOrigin: true, secure: true },
      },
    },
    build: {
      target: 'es2022',
      sourcemap: true,
    },
    test: {
      environment: 'jsdom',
      setupFiles: ['./src/test/setup.ts'],
      css: false,
      restoreMocks: true,
    },
  };
});
