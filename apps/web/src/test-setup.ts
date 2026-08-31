import { vi } from "vitest";

// jsdom deliberately has no WebGL implementation. The portal component treats
// an unavailable context as a normal fallback, so tests should model that
// browser capability instead of emitting one console error per render.
if (typeof HTMLCanvasElement !== "undefined") {
  Object.defineProperty(HTMLCanvasElement.prototype, "getContext", {
    configurable: true,
    value: vi.fn(() => null),
  });
}
