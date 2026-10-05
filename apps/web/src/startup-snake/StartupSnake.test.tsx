// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const motion = vi.hoisted(() => ({ timer: vi.fn() }));
vi.mock("animejs", () => ({ createTimer: motion.timer }));
vi.mock("../animations", () => ({ animate: () => ({ cancel: vi.fn() }), prefersReducedMotion: () => true }));
import { StartupSnake } from "./StartupSnake";

beforeEach(() => {
  motion.timer.mockImplementation(() => ({ cancel: vi.fn(), pause: vi.fn() }));
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
    setTransform: vi.fn(), clearRect: vi.fn(), beginPath: vi.fn(), roundRect: vi.fn(), arc: vi.fn(), moveTo: vi.fn(),
    quadraticCurveTo: vi.fn(), fill: vi.fn(), stroke: vi.fn(),
    createLinearGradient: vi.fn(() => ({ addColorStop: vi.fn() })), drawImage: vi.fn(),
  } as unknown as CanvasRenderingContext2D);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.clearAllMocks(); });

describe("startup snake lifecycle", () => {
  it("does no recurring work until explicitly started, then cancels on pause and unmount", () => {
    const view = render(<StartupSnake />);
    expect(motion.timer).not.toHaveBeenCalled();
    fireEvent.keyDown(screen.getByRole("region", { name: "Мини-игра Змейка" }), { key: " " });
    expect(motion.timer).toHaveBeenCalledOnce();
    expect(motion.timer.mock.calls[0][0].frameRate).toBe(30);
    const timer = motion.timer.mock.results[0].value;
    fireEvent.keyDown(screen.getByRole("region", { name: "Мини-игра Змейка" }), { key: "Escape" });
    expect(timer.cancel).toHaveBeenCalledOnce();
    fireEvent.keyDown(screen.getByRole("region", { name: "Мини-игра Змейка" }), { key: " " });
    const resumed = motion.timer.mock.results[1].value;
    view.unmount();
    expect(resumed.cancel).toHaveBeenCalledOnce();
  });

  it("stops the game as soon as startup becomes ready", () => {
    const view = render(<StartupSnake />);
    fireEvent.keyDown(screen.getByRole("region", { name: "Мини-игра Змейка" }), { key: " " });
    const timer = motion.timer.mock.results[0].value;
    view.rerender(<StartupSnake available={false} />);
    expect(timer.cancel).toHaveBeenCalledOnce();
    expect(screen.getByText("Iris готова")).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
    fireEvent.keyDown(screen.getByRole("region", { name: "Мини-игра Змейка" }), { key: " " });
    expect(motion.timer).toHaveBeenCalledOnce();
  });

  it("pauses when the window loses focus without resuming automatically", () => {
    render(<StartupSnake />);
    fireEvent.keyDown(screen.getByRole("region", { name: "Мини-игра Змейка" }), { key: " " });
    const timer = motion.timer.mock.results[0].value;
    fireEvent(window, new Event("blur"));
    expect(timer.cancel).toHaveBeenCalledOnce();
    expect(screen.getByText("Игра приостановлена")).toBeTruthy();
    fireEvent(window, new Event("focus"));
    expect(motion.timer).toHaveBeenCalledOnce();
  });
});
