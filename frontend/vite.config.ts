import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  build: {
    rollupOptions: {
      output: {
        // Vendors pesados a chunks propios (cachean estable entre deploys);
        // las páginas ya se separan solas por React.lazy en App.tsx.
        manualChunks: {
          react: ["react", "react-dom", "react-router-dom"],
          charts: ["recharts"],
          i18n: ["i18next", "react-i18next"],
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        // Default to the local backend; `VITE_PROXY_TARGET` lets the prod-proxy launch
        // config point the dev server at prod for verification against real data.
        target: process.env.VITE_PROXY_TARGET || "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
