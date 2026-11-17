import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Le frontend construit va dans build/frontend/, d'où le backend le sert.
// En développement, Vite renvoie les appels /api vers le backend.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "../build/frontend", emptyOutDir: true },
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
});
