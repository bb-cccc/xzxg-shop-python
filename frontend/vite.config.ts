import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/api': {
        // Python Compose publishes the API on 8081. Override with
        // VITE_API_TARGET when running the Go service on 8080.
        target: process.env.VITE_API_TARGET ?? 'http://localhost:8081',
        changeOrigin: true
      }
    }
  }
});
