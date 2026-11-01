// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { getStartupProgress } from "../startup";
import type { ReadinessResponse } from "../types";
import { StartupProgress } from "./StartupProgress";
import { StartupScreen } from "./StartupScreen";

const loading: ReadinessResponse = { phase: "text_ready", text_chat: "ready", stt: "ready", tts: "loading", vad: "ready", live_ready: false, errors: [] };
const progress = getStartupProgress("ready", loading, false);
afterEach(() => cleanup());

describe("startup progress feedback", () => {
  it("keeps one current loading status with no details control or stage labels", () => {
    const { container } = render(<StartupScreen status="ready" stage={2} progress={progress} subdetail={progress.detail} />);
    expect(screen.getByText("Подготавливаю голос Iris")).toBeVisible();
    expect(container.querySelectorAll(".startup-content p")).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "Что загружается" })).toBeNull();
    expect(screen.queryByRole("list", { name: "Этапы запуска" })).toBeNull();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "4");
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuemax", "5");
  });
  it("shows an indeterminate meter without fabricated ARIA values", () => {
    render(<StartupProgress progress={getStartupProgress("starting", null, true)} />);
    expect(screen.getByRole("progressbar")).not.toHaveAttribute("aria-valuenow");
  });
  it("stops at the last confirmed progress on failure", () => {
    const { rerender, container } = render(<StartupProgress progress={progress} />);
    const before = [...container.querySelectorAll<HTMLElement>(".startup-progress-fill")].map(el => el.style.width);
    rerender(<StartupProgress progress={getStartupProgress("crashed", loading, false)} />);
    expect([...container.querySelectorAll<HTMLElement>(".startup-progress-fill")].map(el => el.style.width)).toEqual(before);
    expect(screen.getByRole("progressbar")).not.toHaveAttribute("aria-valuenow");
  });
});
