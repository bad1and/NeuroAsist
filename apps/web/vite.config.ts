import { defineConfig } from "vite";

export default defineConfig(({ mode }) => ({
  build: {
    rollupOptions: {
      input: mode === "preview-tools"
        ? { index: "index.html", designPack: "design-pack.html", startupPreview: "startup-preview.html", startupGamePreview: "startup-game-preview.html" }
        : { index: "index.html" },
    },
  },
}));
