// @vitest-environment jsdom
import { createRef } from "react";
import { act, cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const motion = vi.hoisted(() => ({ reduced: vi.fn(() => false), create: vi.fn() }));
vi.mock("../animations", () => ({
  isTestEnvironment: () => false,
  prefersReducedMotion: motion.reduced,
  createTimeline: motion.create,
  animate: () => ({ cancel: vi.fn() }),
}));
import { StartupScreen } from "./StartupScreen";

let frames: Map<number, FrameRequestCallback>;
let frameId: number;
beforeEach(() => {
  motion.reduced.mockReturnValue(false);
  motion.create.mockImplementation((options?: { onComplete?: () => void }) => ({
    add: vi.fn(), cancel: vi.fn(), complete: options?.onComplete,
  }));
  frames = new Map();
  frameId = 0;
  vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => {
    frames.set(++frameId, callback);
    return frameId;
  });
  vi.spyOn(window, "cancelAnimationFrame").mockImplementation((id) => { frames.delete(id); });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.clearAllMocks(); });

function nextCompletedTimeline() {
  const timelines = motion.create.mock.results.map((result) => result.value).filter((timeline) => timeline.complete);
  return timelines[timelines.length - 1];
}
function finishPetals() {
  for (let index = 0; index < 3; index += 1) act(() => nextCompletedTimeline().complete());
}
function paintFrame() {
  const pending = [...frames.values()];
  frames.clear();
  act(() => pending.forEach((callback) => callback(0)));
}

describe("startup completion choreography", () => {
  it.each([false, true])("plays the finale before mounting the interface even if ready on first render (reduced=%s)", (reduced) => {
    motion.reduced.mockReturnValue(reduced);
    const target = createRef<HTMLDivElement>();
    const onReveal = vi.fn();
    const onComplete = vi.fn();
    const { container } = render(<StartupScreen status="ready" stage={3} revealTarget={target}
      onReveal={onReveal} onComplete={onComplete} />);
    finishPetals();
    expect(container.querySelector(".startup-screen")?.getAttribute("data-phase")).toBe("finishing");
    expect(onReveal).not.toHaveBeenCalled();
    expect(onComplete).not.toHaveBeenCalled();

    const finale = nextCompletedTimeline();
    act(() => finale.complete());
    expect(onReveal).toHaveBeenCalledOnce();
    expect(container.querySelector(".startup-screen")?.getAttribute("data-phase")).toBe("preparing");
    paintFrame();
    expect(nextCompletedTimeline()).toBe(finale);
    target.current = document.createElement("div");
    paintFrame();
    expect(nextCompletedTimeline()).toBe(finale);
    paintFrame();
    expect(container.querySelector(".startup-screen")?.getAttribute("data-phase")).toBe("revealing");
    const fade = nextCompletedTimeline();
    expect(fade).not.toBe(finale);
    expect(onComplete).not.toHaveBeenCalled();
    act(() => fade.complete());
    expect(onComplete).toHaveBeenCalledOnce();
  });

  it("does not reveal the interface if startup fails during the finale", () => {
    const onReveal = vi.fn();
    const onComplete = vi.fn();
    const { rerender, container } = render(<StartupScreen status="ready" stage={3}
      onReveal={onReveal} onComplete={onComplete} />);
    finishPetals();
    const finale = nextCompletedTimeline();
    rerender(<StartupScreen status="failed" stage={3} onReveal={onReveal} onComplete={onComplete} />);
    expect(finale.cancel).toHaveBeenCalledOnce();
    act(() => finale.complete());
    expect(container.querySelector(".startup-screen")?.getAttribute("data-phase")).toBe("loading");
    expect(onReveal).not.toHaveBeenCalled();
    expect(onComplete).not.toHaveBeenCalled();
  });

  it("cancels the handoff if the core fails while the interface is fading in", () => {
    const onComplete = vi.fn();
    const { rerender, container } = render(<StartupScreen status="ready" stage={3} onComplete={onComplete} />);
    finishPetals();
    act(() => nextCompletedTimeline().complete());
    paintFrame();
    paintFrame();
    const fade = nextCompletedTimeline();
    rerender(<StartupScreen status="failed" stage={3} onComplete={onComplete} />);
    expect(fade.cancel).toHaveBeenCalledOnce();
    act(() => fade.complete());
    expect(onComplete).not.toHaveBeenCalled();
    expect(container.querySelector<HTMLElement>(".startup-screen")?.style.opacity).toBe("1");
  });
});
