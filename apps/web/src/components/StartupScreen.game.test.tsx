// @vitest-environment jsdom
import { useEffect } from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const game = vi.hoisted(() => ({ imported: vi.fn(), mounted: vi.fn(), disposed: vi.fn() }));
vi.mock("../startup-snake/StartupSnake", () => {
  game.imported();
  return { StartupSnake: ({ autoStart }: { autoStart: boolean }) => {
    useEffect(() => { game.mounted(autoStart); return () => { game.disposed(); }; }, []);
    return <section aria-label="Мини-игра Змейка" />;
  } };
});
import { StartupScreen } from "./StartupScreen";

afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("startup mini-game integration", () => {
  it("loads and starts the game only after the user presses the text action", async () => {
    const { container } = render(<StartupScreen status="starting" stage={1} />);
    expect(game.imported).not.toHaveBeenCalled();
    expect(container.querySelector(".startup-game canvas")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Попинать х.." }));
    await waitFor(() => expect(game.mounted).toHaveBeenCalledWith(true));
    expect(game.imported).toHaveBeenCalledOnce();
    expect(screen.queryByRole("button", { name: "Попинать х.." })).toBeNull();
  });

  it("keeps play available through the final logo handoff", async () => {
    const { rerender, unmount } = render(<StartupScreen status="ready" stage={2} />);
    fireEvent.click(screen.getByRole("button", { name: "Попинать х.." }));
    await waitFor(() => expect(game.mounted).toHaveBeenCalledWith(true));
    rerender(<StartupScreen status="ready" stage={3} />);
    expect(game.disposed).not.toHaveBeenCalled();
    unmount();
    expect(game.disposed).toHaveBeenCalledOnce();
    expect(screen.queryByRole("region", { name: "Мини-игра Змейка" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Попинать х.." })).toBeNull();
  });

  it("disposes play on a failed startup and resets the action for another attempt", async () => {
    const { rerender } = render(<StartupScreen status="starting" stage={1} />);
    fireEvent.click(screen.getByRole("button", { name: "Попинать х.." }));
    await waitFor(() => expect(game.mounted).toHaveBeenCalledWith(true));
    rerender(<StartupScreen status="failed" stage={1} />);
    expect(game.disposed).toHaveBeenCalledOnce();
    expect(screen.queryByRole("button", { name: "Попинать х.." })).toBeNull();
    rerender(<StartupScreen status="starting" stage={1} />);
    expect(screen.getByRole("button", { name: "Попинать х.." })).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Мини-игра Змейка" })).toBeNull();
  });

  it.each(["failed", "crashed", "closing"] as const)("has no game action while %s", (status) => {
    render(<StartupScreen status={status} />);
    expect(screen.queryByRole("button", { name: "Попинать х.." })).toBeNull();
  });
});
