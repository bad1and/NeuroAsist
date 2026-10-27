import { readFileSync } from "node:fs";

// Both production and tests compile the same canonical product version.
export const versionDefine = {
  __IRIS_APP_VERSION__: JSON.stringify(readFileSync(new URL("../../VERSION", import.meta.url), "utf8").trim()),
};
