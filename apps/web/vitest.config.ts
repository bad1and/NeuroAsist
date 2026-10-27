import { defineConfig } from "vitest/config";
import { versionDefine } from "./build-version";

export default defineConfig({
  resolve: { alias: { "@": new URL("./src", import.meta.url).pathname.replace(/^\/(.:\/)/, "$1") } },
  define: versionDefine,
  test: {
    setupFiles: ["./src/test-setup.ts"],
  },
});
