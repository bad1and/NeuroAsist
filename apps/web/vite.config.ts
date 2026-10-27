import { defineConfig } from "vite";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig(({ mode }) => ({
  plugins: [tailwindcss()],
  resolve: { alias: { "@": new URL("./src", import.meta.url).pathname.replace(/^\/(.:\/)/, "$1") } },
  build: {
    rollupOptions: {
      input: mode === "preview-tools"
        ? { index: "index.html", designPack: "design-pack.html", startupPreview: "startup-preview.html", startupGamePreview: "startup-game-preview.html" }
        : { index: "index.html" },
    },
  },
}));
