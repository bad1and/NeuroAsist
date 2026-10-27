// @vitest-environment jsdom
import { cleanup, render, screen, act } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { usePresence } from "./usePresence";
import { animate, prefersReducedMotion } from "./core";

vi.mock("./core", () => ({
  animate: vi.fn(() => ({ cancel: vi.fn() })),
  prefersReducedMotion: vi.fn(() => false), isTestEnvironment: () => false,
}));
function Popup({ open }: { open: boolean }) {
  const popup = usePresence<HTMLDivElement>(open);
  return popup.present ? <div ref={popup.ref} data-testid="popup" aria-hidden={!open}>Menu</div> : null;
}
afterEach(() => { cleanup(); vi.clearAllMocks(); });

it("keeps closing content mounted and ignores completion from an interrupted exit", () => {
  const view = render(<Popup open />);
  view.rerender(<Popup open={false} />);
  expect(screen.getByTestId("popup").getAttribute("aria-hidden")).toBe("true");
  const close = vi.mocked(animate).mock.lastCall![1];
  view.rerender(<Popup open />);
  act(() => (close.onComplete as () => void)());
  expect(screen.getByTestId("popup").getAttribute("aria-hidden")).toBe("false");
  view.rerender(<Popup open={false} />);
  act(() => (vi.mocked(animate).mock.lastCall![1].onComplete as () => void)());
  expect(screen.queryByTestId("popup")).toBeNull();
});

it("uses a short fade without displacement for reduced motion", () => {
  vi.mocked(prefersReducedMotion).mockReturnValue(true);
  render(<Popup open />);
  expect(vi.mocked(animate).mock.lastCall![1]).toMatchObject({ translateY: 0, duration: 100 });
  expect(screen.getByTestId("popup").style.transform).toBe("translateY(0px)");
  vi.mocked(prefersReducedMotion).mockReturnValue(false);
});
