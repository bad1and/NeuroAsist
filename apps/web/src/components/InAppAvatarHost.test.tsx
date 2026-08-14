// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const desktop = vi.hoisted(() => ({
  listenForAvatarLayoutInvalidation: vi.fn(),
  setAvatarInAppBounds: vi.fn(),
  setAvatarInAppVisible: vi.fn(),
}));

vi.mock("../desktop", () => desktop);

import { InAppAvatarHost } from "./InAppAvatarHost";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => { resolve = next; });
  return { promise, resolve };
}

describe("InAppAvatarHost", () => {
  beforeEach(() => {
    desktop.listenForAvatarLayoutInvalidation.mockResolvedValue(() => undefined);
    desktop.setAvatarInAppBounds.mockResolvedValue(undefined);
    desktop.setAvatarInAppVisible.mockResolvedValue(undefined);
    Object.defineProperty(HTMLElement.prototype, "getBoundingClientRect", {
      configurable: true,
      value: () => ({ left: 18, top: 24, width: 220, height: 360 }),
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("maps the native avatar slot to physical pixels before revealing it", async () => {
    Object.defineProperty(window, "devicePixelRatio", { configurable: true, value: 1.5 });
    render(<InAppAvatarHost />);
    await vi.waitFor(() => expect(desktop.setAvatarInAppVisible).toHaveBeenCalledWith(true, expect.any(Number)));
    expect(desktop.setAvatarInAppBounds).toHaveBeenCalledWith(expect.objectContaining({
      x: 27, y: 36, width: 330, height: 540,
    }));
    const revision = desktop.setAvatarInAppBounds.mock.calls[0][0].revision;
    expect(desktop.setAvatarInAppVisible).toHaveBeenCalledWith(true, revision);
  });

  it("hides the native popup when its chat host unmounts", () => {
    const { unmount } = render(<InAppAvatarHost />);
    unmount();
    expect(desktop.setAvatarInAppVisible).toHaveBeenCalledWith(false, expect.any(Number));
  });

  it("does not reveal a popup after an in-flight bounds update unmounts", async () => {
    const bounds = deferred<void>();
    desktop.setAvatarInAppBounds.mockReturnValueOnce(bounds.promise);
    const { unmount } = render(<InAppAvatarHost />);

    unmount();
    bounds.resolve();
    await Promise.resolve();
    await Promise.resolve();

    expect(desktop.setAvatarInAppVisible).not.toHaveBeenCalledWith(true, expect.any(Number));
  });

  it("coalesces native layout invalidations into one animation-frame sync", async () => {
    let invalidate: (() => void) | undefined;
    desktop.listenForAvatarLayoutInvalidation.mockImplementation(async (listener: () => void) => {
      invalidate = listener;
      return () => undefined;
    });
    let frameCallback: FrameRequestCallback | undefined;
    const requestFrame = vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => {
      frameCallback = callback;
      return 1;
    });

    render(<InAppAvatarHost />);
    await vi.waitFor(() => expect(invalidate).toBeTypeOf("function"));
    desktop.setAvatarInAppBounds.mockClear();
    invalidate?.();
    invalidate?.();

    expect(requestFrame).toHaveBeenCalledTimes(1);
    expect(desktop.setAvatarInAppBounds).not.toHaveBeenCalled();
    frameCallback?.(0);
    expect(desktop.setAvatarInAppBounds).toHaveBeenCalledTimes(1);
    requestFrame.mockRestore();
  });
});
