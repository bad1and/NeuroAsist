// @vitest-environment jsdom
import { beforeEach, expect, it, vi } from "vitest";
import { animateNotification } from "./notifications";
import { animate, prefersReducedMotion } from "./core";

vi.mock("./core", () => ({
  animate: vi.fn(() => ({ cancel: vi.fn() })),
  isTestEnvironment: () => false,
  prefersReducedMotion: vi.fn(() => false),
}));

beforeEach(() => { vi.clearAllMocks(); vi.mocked(prefersReducedMotion).mockReturnValue(false); });

it("slides an opaque full-size toast from outside the viewport to its resting position", () => {
  const card = document.createElement("div");
  vi.spyOn(card, "getBoundingClientRect").mockReturnValue({ left: window.innerWidth - 430 } as DOMRect);
  animateNotification(card, "enter");
  const entry = vi.mocked(animate).mock.calls[0][1];
  expect(entry).toMatchObject({ opacity: 1, translateX: [446, 0], scale: 1, duration: 420 });
  expect(typeof entry.ease).toBe("function");
  const finish = vi.fn();
  animateNotification(card, "exit", finish);
  const exit = vi.mocked(animate).mock.calls[1][1];
  expect(exit).toMatchObject({ opacity: 1, translateX: 446, scale: 1, duration: 190 });
  (exit.onComplete as () => void)();
  expect(finish).toHaveBeenCalledOnce();
});

it("uses only a short fade for reduced motion and resumes interrupted entrances", () => {
  const card = document.createElement("div");
  vi.mocked(prefersReducedMotion).mockReturnValue(true);
  animateNotification(card, "enter");
  expect(vi.mocked(animate).mock.calls[0][1]).toMatchObject({ translateX: 0, scale: 1, duration: 120 });
  vi.mocked(prefersReducedMotion).mockReturnValue(false);
  card.style.opacity = "0.5";
  // JSDOM does not compute CSS transform matrices.
  card.style.transform = "none";
  animateNotification(card, "enter");
  expect(vi.mocked(animate).mock.calls[1][1]).toMatchObject({ opacity: 1, translateX: 0, scale: 1 });
});

it("uses the same viewport-edge slide for the conversation panel", () => {
  const card = document.createElement("div");
  vi.spyOn(card, "getBoundingClientRect").mockReturnValue({ left: window.innerWidth - 355 } as DOMRect);
  animateNotification(card, "enter");
  expect(vi.mocked(animate).mock.calls[0][1]).toMatchObject({ translateX: [371, 0] });
  card.className = "conversation-surface";
  animateNotification(card, "enter");
  expect(vi.mocked(animate).mock.calls[1][1]).toMatchObject({ translateX: [371, 0], duration: 420, scale: 1 });
});
