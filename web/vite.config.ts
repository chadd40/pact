import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Minimal ambient declaration so `process.env` typechecks without pulling in
// @types/node (this config runs in Node at build time; Vite reads it via esbuild).
declare const process: { env: Record<string, string | undefined> };

// Dev proxy: forward the FastAPI surface (/api and /demo) to the backend so the
// SPA can talk to it without CORS while running on Vite's dev server.
export default defineConfig({
  // Base path: default "/" for dev + the Tauri desktop bundle (Tauri's
  // beforeBuildCommand runs `npm run build` with no env). The GitHub Pages
  // workflow sets PACT_PAGES_BASE=/pact/ so the project site resolves assets
  // under https://chadd40.github.io/pact/.
  base: process.env.PACT_PAGES_BASE || "/",
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
