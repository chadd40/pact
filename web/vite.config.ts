import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev proxy: forward the FastAPI surface (/api and /demo) to the backend so the
// SPA can talk to it without CORS while running on Vite's dev server.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
      "/demo": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
