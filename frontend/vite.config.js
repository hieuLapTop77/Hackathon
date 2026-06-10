import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");

  return {
    plugins: [react()],
    server: {
      port: 3000,
      proxy: {
        "/flights": {
          target: "http://host.docker.internal:8000",
          changeOrigin: true,
        },
        "/summary": {
          target: "http://host.docker.internal:8000",
          changeOrigin: true,
        },
        "/health": {
          target: "http://host.docker.internal:8000",
          changeOrigin: true,
        },
        "/models": {
          target: "http://host.docker.internal:8000",
          changeOrigin: true,
        },
        "/routes": {
          target: "http://host.docker.internal:8000",
          changeOrigin: true,
        },
        "/db/": {
          target: "http://host.docker.internal:8000",
          changeOrigin: true,
        },
        "/optimize": {
          target: "http://host.docker.internal:8000",
          changeOrigin: true,
        },
        "/predict": {
          target: "http://host.docker.internal:8000",
          changeOrigin: true,
        },
        "/upload": {
          target: "http://host.docker.internal:8000",
          changeOrigin: true,
        },
      },
    },
    build: {
      outDir: "dist",
      rollupOptions: {
        output: {
          manualChunks: undefined,
        },
      },
    },
  };
});
