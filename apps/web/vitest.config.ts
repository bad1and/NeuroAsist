import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: { alias: { "@": new URL("./src", import.meta.url).pathname.replace(/^\/(.:\/)/, "$1") } },
  test: {
    setupFiles: ["./src/test-setup.ts"],
  },
});
