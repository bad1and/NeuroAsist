// @vitest-environment jsdom
import { cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import petals from "../brand/iris-petals.json";

const motion = vi.hoisted(() => ({ reduced: vi.fn(() => false), create: vi.fn() }));
vi.mock("../animations", () => ({
  isTestEnvironment: () => false,
  prefersReducedMotion: motion.reduced,
  createTimeline: motion.create,
}));
import { IrisPetals } from "./IrisPetals";

beforeEach(() => {
  motion.reduced.mockReturnValue(false);
  motion.create.mockImplementation(() => ({ add: vi.fn(), cancel: vi.fn() }));
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("startup waiting motion", () => {
  it("keeps the first petal moving when a newly formed petal joins", () => {
    const { rerender } = render(<IrisPetals unfolding withWordmark idlePetals={1} />);
    const first = motion.create.mock.results[0].value;
    expect(motion.create).toHaveBeenCalledTimes(1);
    rerender(<IrisPetals unfolding withWordmark idlePetals={2} />);
    expect(motion.create).toHaveBeenCalledTimes(2);
    expect(first.cancel).not.toHaveBeenCalled();
  });

  it("stops waiting cycles and restores the source contours on ordinary disposal", () => {
    const { rerender, container, unmount } = render(<IrisPetals unfolding idlePetals={2} />);
    const cycles = motion.create.mock.results.map((result) => result.value);
    rerender(<IrisPetals unfolding idlePetals={0} />);
    cycles.forEach((cycle) => expect(cycle.cancel).toHaveBeenCalledOnce());
    [0, 1].forEach((index) => expect(container.querySelector(`[data-petal-shape="${index}"]`)?.getAttribute("d")).toBe(petals[index].d));
    rerender(<IrisPetals unfolding idlePetals={1} />);
    const restarted = motion.create.mock.results[2].value;
    unmount();
    expect(restarted.cancel).toHaveBeenCalledOnce();
  });

  it("hands the current waiting pose to the finale without snapping", () => {
    const { rerender, container } = render(<IrisPetals unfolding idlePetals={1} />);
    const petal = container.querySelector<SVGGElement>("[data-petal='0']")!;
    const path = petal.querySelector("path")!;
    path.setAttribute("d", "current animated contour");
    petal.style.transform = "translateY(-1px) rotate(0.5deg)";
    rerender(<IrisPetals unfolding idlePetals={0} settling />);
    expect(motion.create.mock.results[0].value.cancel).toHaveBeenCalledOnce();
    expect(path.getAttribute("d")).toBe("current animated contour");
    expect(petal.style.transform).toBe("translateY(-1px) rotate(0.5deg)");
  });

  it("does not loop spatial motion when reduced motion is enabled", () => {
    motion.reduced.mockReturnValue(true);
    render(<IrisPetals idlePetals={3} />);
    expect(motion.create).not.toHaveBeenCalled();
  });
});
