/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Single-origin in dev: proxy API calls to the backend (spec §9 frontend note).
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/setupTests.ts"],
    css: true,
    // Unit/component tests live under src/; Playwright e2e (./e2e/*.spec.ts) runs
    // separately via `npm run test:e2e` and must not be collected by vitest.
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
  },
});
