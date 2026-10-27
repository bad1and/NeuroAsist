import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { normalizePath, type Plugin } from "vite";

const versionFile = fileURLToPath(new URL("../../VERSION", import.meta.url));

// Both production and tests compile the same canonical product version.
export const versionDefine = {
  __IRIS_APP_VERSION__: JSON.stringify(readFileSync(versionFile, "utf8").trim()),
};

export function watchAppVersion(): Plugin {
  return {
    name: "iris-app-version",
    configureServer(server) {
      const onVersionChange = (file: string) => {
        if (normalizePath(file) === normalizePath(versionFile)) void server.restart();
      };
      server.watcher.add(versionFile);
      server.watcher.on("change", onVersionChange);
      server.httpServer?.once("close", () => server.watcher.off("change", onVersionChange));
    },
  };
}
