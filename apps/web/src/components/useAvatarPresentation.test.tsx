// @vitest-environment jsdom
import { cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ requestJson: vi.fn().mockResolvedValue({ sent: 1 }) }));
vi.mock("../api", () => api);
vi.mock("../desktop", () => ({ isDesktopApp: () => true }));
import { useAvatarPresentation } from "./useAvatarPresentation";

afterEach(() => { cleanup(); vi.clearAllMocks(); });

it("sends a newer portrait revision when the welcome scene becomes a dialog", async () => {
  const view = renderHook(({ seated }) => useAvatarPresentation(seated, true, "ready"), { initialProps: { seated: true } });
  await waitFor(() => expect(api.requestJson).toHaveBeenCalledTimes(1));
  view.rerender({ seated: false });
  await waitFor(() => expect(api.requestJson).toHaveBeenCalledTimes(2));
  const first = JSON.parse(api.requestJson.mock.calls[0][1].body);
  const second = JSON.parse(api.requestJson.mock.calls[1][1].body);
  expect(first.mode).toBe("welcome_seated");
  expect(second.mode).toBe("portrait");
  expect(second.revision).toBeGreaterThan(first.revision);
});

it("reapplies presentation after renderer recovery and does not command a hidden host", async () => {
  const view = renderHook(({ enabled, phase }) => useAvatarPresentation(true, enabled, phase), { initialProps: { enabled: false, phase: "warming" } });
  expect(api.requestJson).not.toHaveBeenCalled();
  view.rerender({ enabled: true, phase: "warming" });
  view.rerender({ enabled: true, phase: "ready" });
  await waitFor(() => expect(api.requestJson).toHaveBeenCalledTimes(2));
});
