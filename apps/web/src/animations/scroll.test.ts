// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { installSmoothWheel } from "./scroll";
import { animate, prefersReducedMotion } from "./core";

vi.mock("./core", () => ({
  animate: vi.fn(() => ({ cancel: vi.fn() })),
  prefersReducedMotion: vi.fn(() => false),
}));
let root: HTMLDivElement;
let list: HTMLDivElement;
let cleanup: () => void;
function wheel(deltaY: number, extra: WheelEventInit = {}, target: HTMLElement = list) {
  const event = new WheelEvent("wheel", { deltaY, bubbles: true, cancelable: true, ...extra });
  target.dispatchEvent(event);
  return event;
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(prefersReducedMotion).mockReturnValue(false);
  root = document.createElement("div"); list = document.createElement("div");
  list.style.overflowY = "auto";
  Object.defineProperties(list, { scrollHeight: { value: 3000 }, clientHeight: { value: 600 } });
  root.append(list); document.body.append(root);
  cleanup = installSmoothWheel(root);
});
afterEach(() => { cleanup(); root.remove(); });

it("accumulates coarse wheel input with a short bounded tail and reverses immediately", () => {
  list.scrollTop = 500;
  expect(wheel(100).defaultPrevented).toBe(true);
  expect(vi.mocked(animate).mock.calls[0][1]).toMatchObject({ value: 600, duration: 240 });
  wheel(100);
  expect(vi.mocked(animate).mock.calls[1][1]).toMatchObject({ value: 700 });
  wheel(-100);
  expect(vi.mocked(animate).mock.calls[2][1]).toMatchObject({ value: 400 });
  for (let i = 0; i < 10; i++) wheel(120);
  expect(Number(vi.mocked(animate).mock.lastCall?.[1].value)).toBeLessThanOrEqual(980);
});

it("preserves precision devices, zoom, horizontal gestures, reduced motion and field input", () => {
  expect(wheel(8.5).defaultPrevented).toBe(false);
  expect(wheel(100, { ctrlKey: true }).defaultPrevented).toBe(false);
  expect(wheel(100, { shiftKey: true }).defaultPrevented).toBe(false);
  expect(wheel(100, { deltaX: 70 }).defaultPrevented).toBe(false);
  const input = document.createElement("textarea"); list.append(input);
  expect(wheel(100, {}, input).defaultPrevented).toBe(false);
  vi.mocked(prefersReducedMotion).mockReturnValue(true);
  expect(wheel(100).defaultPrevented).toBe(false);
  expect(animate).not.toHaveBeenCalled();
});

it.each([15, 33.333, 53, 79.5, 106.666])("smooths real mouse step %s without divisibility assumptions", delta => {
  expect(wheel(delta).defaultPrevented).toBe(true);
  expect(vi.mocked(animate).mock.lastCall?.[1]).toMatchObject({ value: delta, duration: 240 });
});

it("accepts minor horizontal mouse noise and stops for a precision stream", () => {
  expect(wheel(53, { deltaX: 1.25 }).defaultPrevented).toBe(true);
  const motion = vi.mocked(animate).mock.results[0].value;
  expect(wheel(8.5).defaultPrevented).toBe(false);
  expect(motion.cancel).toHaveBeenCalled();
});

it("keeps nested scrolling local and yields at its boundaries", () => {
  const nested = document.createElement("div"); nested.style.overflowY = "auto";
  Object.defineProperties(nested, { scrollHeight: { value: 400 }, clientHeight: { value: 100 } });
  list.append(nested);
  expect(wheel(100, {}, nested).defaultPrevented).toBe(true);
  const [position, parameters] = vi.mocked(animate).mock.calls[0];
  (position as { value: number }).value = 75;
  (parameters.onUpdate as () => void)();
  expect(nested.scrollTop).toBe(75);
  expect(list.scrollTop).toBe(0);
  nested.scrollTop = 300;
  expect(wheel(100, {}, nested).defaultPrevented).toBe(false);
});

it("cancels on keyboard, pointer, external jumps and unmount", () => {
  wheel(100);
  const first = vi.mocked(animate).mock.results[0].value;
  root.dispatchEvent(new KeyboardEvent("keydown", { key: "PageDown", bubbles: true }));
  expect(first.cancel).toHaveBeenCalled();
  wheel(100);
  const second = vi.mocked(animate).mock.results[1].value;
  list.scrollTop = 900; list.dispatchEvent(new Event("scroll"));
  expect(second.cancel).toHaveBeenCalled();
  wheel(100);
  const third = vi.mocked(animate).mock.results[2].value;
  root.dispatchEvent(new Event("pointerdown", { bubbles: true }));
  expect(third.cancel).toHaveBeenCalled();
  cleanup();
  expect(wheel(100).defaultPrevented).toBe(false);
});
