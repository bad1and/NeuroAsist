// @vitest-environment jsdom
import { act, cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
const mocks = vi.hoisted(() => ({
  draw: vi.fn(), dispose: vi.fn(), pause: vi.fn(), resume: vi.fn(), cancel: vi.fn(),
  createRig: vi.fn(), createTimer: vi.fn(),
}));
vi.mock("./welcome-portrait-rig", () => ({ createWelcomePortraitRig: mocks.createRig }));
vi.mock("animejs", () => ({ createTimer: mocks.createTimer }));
import { ChatWelcomePortrait } from "./ChatWelcomePortrait";

let reduced = false;
let hidden = false;
let motionChanged: () => void;
beforeEach(() => {
  reduced = false;
  hidden = false;
  mocks.createRig.mockReturnValue({ draw: mocks.draw, dispose: mocks.dispose });
  mocks.createTimer.mockReturnValue({ pause: mocks.pause, resume: mocks.resume, cancel: mocks.cancel });
  vi.stubGlobal("matchMedia", () => ({
    get matches() { return reduced; },
    addEventListener: (_: string, listener: () => void) => { motionChanged = listener; },
    removeEventListener: vi.fn(),
  }));
  vi.spyOn(document, "hidden", "get").mockImplementation(() => hidden);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.clearAllMocks(); });

function loadImage(container: HTMLElement) {
  const image = container.querySelector("img")!;
  Object.defineProperties(image, { complete: { value: true }, naturalWidth: { value: 1024 } });
  fireEvent.load(image);
}

it("keeps the static portrait when inactive, reduced motion is requested, or WebGL fails", () => {
  const view = render(<ChatWelcomePortrait active={false} />);
  loadImage(view.container);
  expect(mocks.createRig).not.toHaveBeenCalled();
  reduced = true;
  view.rerender(<ChatWelcomePortrait active />);
  expect(mocks.createRig).not.toHaveBeenCalled();
  mocks.createRig.mockReturnValue(null);
  reduced = false;
  act(() => motionChanged());
  expect(view.container.firstElementChild?.getAttribute("data-animated")).toBe("false");
  expect(mocks.createTimer).not.toHaveBeenCalled();
});

it("pauses the clock in the background and releases the rig when the welcome view hides", () => {
  const view = render(<ChatWelcomePortrait active />);
  loadImage(view.container);
  expect(view.container.firstElementChild?.getAttribute("data-animated")).toBe("true");
  expect(mocks.createTimer).toHaveBeenCalledWith(expect.objectContaining({ frameRate: 30 }));
  mocks.resume.mockClear();
  hidden = true;
  fireEvent(document, new Event("visibilitychange"));
  expect(mocks.pause).toHaveBeenCalled();
  expect(mocks.resume).not.toHaveBeenCalled();
  hidden = false;
  fireEvent(document, new Event("visibilitychange"));
  expect(mocks.resume).toHaveBeenCalledOnce();
  view.rerender(<ChatWelcomePortrait active={false} />);
  expect(mocks.cancel).toHaveBeenCalledOnce();
  expect(mocks.dispose).toHaveBeenCalledOnce();
});

it("returns to the static image immediately when reduced motion or context loss occurs", () => {
  const view = render(<ChatWelcomePortrait active />);
  loadImage(view.container);
  reduced = true;
  act(() => motionChanged());
  expect(view.container.firstElementChild?.getAttribute("data-animated")).toBe("false");
  reduced = false;
  act(() => motionChanged());
  expect(view.container.firstElementChild?.getAttribute("data-animated")).toBe("true");
  fireEvent(view.container.querySelector("canvas")!, new Event("webglcontextlost", { cancelable: true }));
  expect(view.container.firstElementChild?.getAttribute("data-animated")).toBe("false");
  fireEvent(view.container.querySelector("canvas")!, new Event("webglcontextrestored"));
  expect(view.container.firstElementChild?.getAttribute("data-animated")).toBe("true");
  expect(mocks.createRig).toHaveBeenCalledTimes(2);
});
