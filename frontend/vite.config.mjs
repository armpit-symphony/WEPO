import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

function publicReactEnvironment(mode) {
  const loaded = {
    ...loadEnv(mode, process.cwd(), ''),
    ...process.env,
  };
  const exposed = {
    NODE_ENV: mode === 'production' ? 'production' : 'development',
    NODE_DEBUG: loaded.NODE_DEBUG || '',
  };
  for (const [name, value] of Object.entries(loaded)) {
    if (name.startsWith('REACT_APP_')) {
      exposed[name] = value;
    }
  }
  return exposed;
}

export default defineConfig(({ mode }) => ({
  base: './',
  plugins: [
    react({
      include: /\.[jt]sx?$/,
    }),
  ],
  define:
    mode === 'test'
      ? {
          global: 'globalThis',
        }
      : {
          global: 'globalThis',
          'process.env': JSON.stringify(publicReactEnvironment(mode)),
        },
  server: {
    host: '127.0.0.1',
    hmr: process.env.DISABLE_HOT_RELOAD === 'true' ? false : undefined,
  },
  preview: {
    host: '127.0.0.1',
  },
  build: {
    outDir: 'build',
    emptyOutDir: true,
    sourcemap: true,
    rollupOptions: {
      output: {
        entryFileNames: 'static/js/main.[hash].js',
        chunkFileNames: 'static/js/[name].[hash].js',
        assetFileNames: (assetInfo) => {
          const name = assetInfo.names?.[0] || assetInfo.name || '';
          if (name.endsWith('.css')) {
            return 'static/css/main.[hash][extname]';
          }
          return 'static/media/[name].[hash][extname]';
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/vitest.setup.js'],
    restoreMocks: false,
    mockReset: false,
    clearMocks: false,
  },
}));
