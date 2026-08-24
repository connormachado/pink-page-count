import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// The API is same-origin in production (Phase 4 serves the built files from the
// FastAPI app). In dev the two run on different ports, so Vite proxies /api to
// the backend. This is dev-only config: DECISIONS.md 5 says no CORS middleware
// is installed at all, and this is how that stays true.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8420",
        changeOrigin: false,
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test-setup.ts",
    css: false,
  },
});
