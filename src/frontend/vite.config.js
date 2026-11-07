import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vite';

export default defineConfig({
  resolve: {
    alias: {
      // Unused hex layers pull in h3-js; swap it for a tiny stub.
      'h3-js': fileURLToPath(new URL('./src/stubs/h3-js.js', import.meta.url)),
    },
  },
  server: {
    host: true, // expose on LAN so you can test on your phone
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
  build: {
    chunkSizeWarningLimit: 2500,
    // Keep flag SVGs as separate files so only the flags actually shown get downloaded.
    assetsInlineLimit: (file) => (file.includes('flag-icons') ? false : undefined),
  },
});
