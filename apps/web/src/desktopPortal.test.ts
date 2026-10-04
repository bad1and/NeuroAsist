// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
const invoke = vi.hoisted(() => vi.fn());
vi.mock("@tauri-apps/api/core", () => ({ invoke }));
import { openApiKeyPortal } from "./desktop";

afterEach(() => {
  delete window.__TAURI_INTERNALS__;
  vi.restoreAllMocks();
  invoke.mockReset();
});

it.each([
  ["deepseek", "https://platform.deepseek.com/api_keys"],
  ["tavily", "https://app.tavily.com/home"],
] as const)("opens the official %s portal in a separate browser tab", async (provider, url) => {
  const open = vi.spyOn(window, "open").mockReturnValue(null);
  await openApiKeyPortal(provider);
  expect(open).toHaveBeenCalledExactlyOnceWith(url, "_blank", "noopener,noreferrer");
  expect(invoke).not.toHaveBeenCalled();
});

it("uses the desktop command and propagates opening failures", async () => {
  window.__TAURI_INTERNALS__ = {} as typeof window.__TAURI_INTERNALS__;
  const open = vi.spyOn(window, "open").mockReturnValue(null);
  invoke.mockRejectedValue(new Error("Cannot open browser"));
  await expect(openApiKeyPortal("tavily")).rejects.toThrow("Cannot open browser");
  expect(invoke).toHaveBeenCalledExactlyOnceWith("open_api_key_portal", { provider: "tavily" });
  expect(open).not.toHaveBeenCalled();
});
