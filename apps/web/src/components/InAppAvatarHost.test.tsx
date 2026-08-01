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
    Object.defineProperty(HTMLElement.prototype, "getBoundingClientRect", {
      configurable: true,
      value: () => ({ left: 18, top: 24, width: 220, height: 360 }),
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("does not reveal a popup after its chat host has unmounted", async () => {
    const bounds = deferred<void>();
    desktop.setAvatarInAppBounds.mockReturnValue(bounds.promise);

    const { unmount } = render(<InAppAvatarHost />);
    expect(desktop.setAvatarInAppBounds).toHaveBeenCalledTimes(1);

    unmount();
    expect(desktop.setAvatarInAppVisible).toHaveBeenCalledWith(false, expect.any(Number));

    bounds.resolve();
    await Promise.resolve();
    await Promise.resolve();

    expect(desktop.setAvatarInAppVisible).not.toHaveBeenCalledWith(true, expect.any(Number));
  });
});
