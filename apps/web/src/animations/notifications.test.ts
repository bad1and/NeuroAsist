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

it("matches the existing notification slide, scale, timings and easing", () => {
  const card = document.createElement("div");
  animateNotification(card, "enter");
  const entry = vi.mocked(animate).mock.calls[0][1];
  expect(entry).toMatchObject({ opacity: [0, 1], translateX: [28, 0], scale: [0.96, 1], duration: 220 });
  expect(typeof entry.ease).toBe("function");
  const finish = vi.fn();
  animateNotification(card, "exit", finish);
  const exit = vi.mocked(animate).mock.calls[1][1];
  expect(exit).toMatchObject({ opacity: 0, translateX: 28, scale: 0.96, duration: 190 });
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
  card.style.transform = "translateX(14px) scale(0.98)";
  animateNotification(card, "enter");
  expect(vi.mocked(animate).mock.calls[1][1]).toMatchObject({ opacity: 1, translateX: 0, scale: 1 });
});
