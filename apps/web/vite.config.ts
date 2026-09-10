import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";
import path from "path";

// https://vitejs.dev/config/
export default defineConfig({
  server: {
    host: "::",
    port: 5173,
    // En dev, el backend corre aparte (uvicorn, normalmente :8000). El
    // proxy evita configurar VITE_API_URL a mano y hace que las cookies de
    // sesión (httpOnly, SameSite=Lax) viajen same-origin desde el punto de
    // vista del navegador — sin esto habría que depender de CORS +
    // credentials cruzados solo para desarrollar localmente.
    proxy: {
      "/portal": {
        target: process.env.VITE_BACKEND_URL || "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "./src"),
    },
  },
  build: {
    outDir: "dist",
  },
});
