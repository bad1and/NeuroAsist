// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { CustomSelect } from "./CustomSelect";
import { animate } from "../animations/core";

vi.mock("../animations/core", () => ({
  animate: vi.fn(() => ({ cancel: vi.fn() })),
  runSafeAnimation: () => ({ cancel: vi.fn() }),
  prefersReducedMotion: () => false, isTestEnvironment: () => false,
}));
afterEach(() => { cleanup(); vi.clearAllMocks(); });

it("reveals height without moving or fading the joined shell", () => {
  const view = render(<CustomSelect value="one"><option value="one">Первый</option><option value="two">Второй</option></CustomSelect>);
  fireEvent.click(screen.getByRole("button", { name: "Первый" }));
  const popup = view.container.querySelector<HTMLElement>(".custom-select-popup")!;
  const motion = vi.mocked(animate).mock.calls.find(([target]) => target === popup)![1];
  expect(Number(motion.height)).toBeGreaterThan(0);
  expect(motion).not.toHaveProperty("translateY");
  expect(motion).not.toHaveProperty("opacity");
  expect(popup.style.transform).toBe("");
  expect(popup.querySelector(".custom-select-reveal > [role='listbox']")).not.toBeNull();
});

it("reopens from the interrupted height and ignores stale exit completion", () => {
  const view = render(<CustomSelect value="one"><option value="one">Первый</option><option value="two">Второй</option></CustomSelect>);
  const trigger = screen.getByRole("button", { name: "Первый" });
  fireEvent.click(trigger);
  const popup = view.container.querySelector<HTMLElement>(".custom-select-popup")!;
  popup.style.height = "40px";
  fireEvent.click(trigger);
  const closing = vi.mocked(animate).mock.calls.filter(([target]) => target === popup);
  const close = closing[closing.length - 1][1];
  expect(popup).toHaveAttribute("inert");
  fireEvent.click(trigger);
  expect(popup.style.height).toBe("40px");
  act(() => (close.onComplete as () => void)());
  expect(screen.getByRole("listbox")).toBeInTheDocument();
  fireEvent.click(trigger);
  const calls = vi.mocked(animate).mock.calls.filter(([target]) => target === popup);
  act(() => (calls[calls.length - 1][1].onComplete as () => void)());
  expect(view.container.querySelector(".custom-select-popup")).toBeNull();
});
