import { defineConfig } from "vite";
import tailwindcss from "@tailwindcss/vite";
import { versionDefine, watchAppVersion } from "./build-version";

export default defineConfig(({ mode }) => ({
  plugins: [tailwindcss(), watchAppVersion()],
  resolve: { alias: { "@": new URL("./src", import.meta.url).pathname.replace(/^\/(.:\/)/, "$1") } },
  define: versionDefine,
  build: {
    rollupOptions: {
      input: mode === "preview-tools"
        ? { index: "index.html", designPack: "design-pack.html", startupPreview: "startup-preview.html", startupGamePreview: "startup-game-preview.html", changelogPreview: "changelog-preview.html" }
        : { index: "index.html" },
    },
  },
}));
