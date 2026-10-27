// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { NavigationDisclosure } from "./NavigationDisclosure";
import { animate, prefersReducedMotion } from "../animations/core";

vi.mock("../animations/core", () => ({
  animate: vi.fn(() => ({ cancel: vi.fn() })),
  prefersReducedMotion: vi.fn(() => false), isTestEnvironment: () => false,
}));
afterEach(() => { cleanup(); vi.clearAllMocks(); vi.mocked(prefersReducedMotion).mockReturnValue(false); });

const menu = (open: boolean) => <div><svg className="settings-nav-chevron" /><NavigationDisclosure id="voice" open={open}><button>Устройства</button></NavigationDisclosure></div>;

it("starts static and makes closing rows inert before hiding them at completion", () => {
  const view = render(menu(true));
  expect(animate).not.toHaveBeenCalled();
  const panel = document.getElementById("voice")!;
  view.rerender(menu(false));
  expect(panel).toHaveAttribute("inert");
  expect(panel.hidden).toBe(false);
  expect(screen.queryByRole("button")).toBeNull();
  const close = vi.mocked(animate).mock.calls.find(([target]) => target === panel)![1];
  act(() => (close.onComplete as () => void)());
  expect(panel.hidden).toBe(true);
  expect(panel.style.height).toBe("");
});

it("reverses from the current height and rejects a stale close callback", () => {
  const view = render(menu(true));
  const panel = document.getElementById("voice")!;
  vi.spyOn(panel, "getBoundingClientRect").mockReturnValue({ height: 66 } as DOMRect);
  view.rerender(menu(false));
  const close = vi.mocked(animate).mock.calls.find(([target]) => target === panel)![1];
  view.rerender(menu(true));
  expect(panel.style.height).toBe("66px");
  act(() => (close.onComplete as () => void)());
  expect(panel.hidden).toBe(false);
  expect(screen.getByRole("button", { name: "Устройства" })).toBeVisible();
  const calls = vi.mocked(animate).mock.calls.filter(([target]) => target === panel);
  const open = calls[calls.length - 1][1];
  expect(Number.isFinite(open.height)).toBe(true);
  act(() => (open.onComplete as () => void)());
  expect(panel.style.height).toBe("");
  expect(panel.style.transform).toBe("");
});

it("settles immediately with reduced motion", () => {
  vi.mocked(prefersReducedMotion).mockReturnValue(true);
  const view = render(menu(false)); view.rerender(menu(true)); view.rerender(menu(false));
  expect(document.getElementById("voice")!.hidden).toBe(true);
  expect(animate).not.toHaveBeenCalled();
});
