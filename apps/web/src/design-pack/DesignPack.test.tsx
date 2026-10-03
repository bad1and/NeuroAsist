// @vitest-environment jsdom
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { DesignPack, FieldSurface } from "./DesignPack";
import { seedStorageKey } from "./materialSeeds";

vi.mock("../animations/core", () => ({
  isTestEnvironment: () => true,
  prefersReducedMotion: () => true,
  animate: () => ({ cancel: vi.fn() }),
}));

afterEach(() => { cleanup(); localStorage.clear(); });

describe("design pack interaction contract", () => {
  it("clears a removed compact choice and its approval while preserving seeds and other approvals", () => {
    localStorage.setItem("iris-design-pack-compact-v1", "sculpted");
    localStorage.setItem("iris-design-pack-lens-v3", JSON.stringify({ compact: "accept", fields: "accept" }));
    localStorage.setItem(seedStorageKey, "42");
    const { unmount } = render(<DesignPack />);
    const compact = screen.getByRole("region", { name: "Маленькие кнопки" });
    expect(within(compact).getByRole("button", { name: "Микрофон" })).toHaveAttribute("data-material-seed", "42");
    expect(within(compact).getByRole("button", { name: "Нравится" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.queryByRole("region", { name: "Варианты маленьких кнопок" })).toBeNull();
    expect(localStorage.getItem("iris-design-pack-compact-v1")).toBeNull();
    expect(localStorage.getItem(seedStorageKey)).toBe("42");
    unmount();
    render(<DesignPack />);
    expect(within(screen.getByRole("region", { name: "Маленькие кнопки" })).getByRole("button", { name: "Нравится" })).toHaveAttribute("aria-pressed", "false");
    expect(within(screen.getByRole("region", { name: "Световая обводка" })).getByRole("button", { name: "Нравится" })).toHaveAttribute("aria-pressed", "true");
  });

  it("applies a seed to samples, persists it, resets button approvals and restores the original material", () => {
    const { unmount } = render(<DesignPack />);
    const section = screen.getByRole("region", { name: "Кнопки действий" });
    fireEvent.click(within(section).getByRole("button", { name: "Нравится" }));
    fireEvent.click(screen.getByRole("button", { name: "Использовать сид 42" }));
    expect(within(section).getAllByRole("button", { name: "Начать диалог" })[0]).toHaveAttribute("data-material-seed", "42");
    expect(within(section).getByRole("button", { name: "Нравится" })).toHaveAttribute("aria-pressed", "false");
    expect(localStorage.getItem(seedStorageKey)).toBe("42");
    unmount();
    render(<DesignPack />);
    expect(screen.getByRole("button", { name: "Использовать сид 42" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "Исходный вид" }));
    expect(within(screen.getByRole("region", { name: "Кнопки действий" })).getAllByRole("button", { name: "Начать диалог" })[0]).not.toHaveAttribute("data-material-seed");
  });

  it("hides the new rim at rest, keeps it after pointer leave while typing, and removes it on blur", () => {
    render(<FieldSurface><input aria-label="Поле" /></FieldSurface>);
    const input = screen.getByRole("textbox");
    const surface = input.parentElement!;
    expect(surface).toHaveAttribute("data-rim-visible", "false");
    fireEvent.pointerEnter(surface);
    expect(surface).toHaveAttribute("data-rim-visible", "true");
    fireEvent.focusIn(input);
    fireEvent.pointerLeave(surface);
    expect(surface).toHaveAttribute("data-rim-visible", "true");
    fireEvent.focusOut(input);
    expect(surface).toHaveAttribute("data-rim-visible", "false");
  });

  it("never lights a disabled field, including focus and pointer events", () => {
    render(<FieldSurface disabled><input aria-label="Недоступно" disabled /></FieldSurface>);
    const input = screen.getByRole("textbox");
    const surface = input.parentElement!;
    fireEvent.pointerEnter(surface);
    fireEvent.pointerDown(surface);
    fireEvent.focusIn(input);
    expect(surface).toHaveAttribute("data-rim-visible", "false");
  });

  it("does not drop the rim when focus moves to another control inside the same field", () => {
    render(<FieldSurface><input aria-label="Поиск" /><button>Очистить</button></FieldSurface>);
    const input = screen.getByRole("textbox");
    fireEvent.focusIn(input);
    fireEvent.focusOut(input, { relatedTarget: screen.getByRole("button") });
    expect(input.parentElement).toHaveAttribute("data-rim-visible", "true");
  });

  it("persists group approvals across reopening without treating unreviewed groups as approved", () => {
    const { unmount } = render(<DesignPack />);
    const section = screen.getByRole("region", { name: "Кнопки действий" });
    fireEvent.click(within(section).getByRole("button", { name: "Нравится" }));
    unmount();
    render(<DesignPack />);
    expect(within(screen.getByRole("region", { name: "Кнопки действий" })).getByRole("button", { name: "Нравится" })).toHaveAttribute("aria-pressed", "true");
    expect(within(screen.getByRole("region", { name: "Световая обводка" })).queryByRole("button", { pressed: true })).toBeNull();
  });

  it("ignores approvals of the removed soft material while preserving field approvals", () => {
    localStorage.setItem("iris-design-pack-lens-v3", JSON.stringify({ buttons: "accept", fields: "accept", variants: { buttons: "soft" } }));
    render(<DesignPack />);
    expect(within(screen.getByRole("region", { name: "Кнопки действий" })).getByRole("button", { name: "Нравится" })).toHaveAttribute("aria-pressed", "false");
    expect(within(screen.getByRole("region", { name: "Световая обводка" })).getByRole("button", { name: "Нравится" })).toHaveAttribute("aria-pressed", "true");
  });

  it("handles malformed saved choices and lets the user try switches and the dropdown", () => {
    localStorage.setItem("iris-design-pack-lens-v3", "broken");
    render(<DesignPack />);
    const toggle = screen.getAllByRole("switch")[0];
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-checked", "false");
    fireEvent.click(screen.getByRole("button", { name: "Iris · основной голос" }));
    fireEvent.click(within(screen.getByRole("listbox")).getByText("Iris · спокойный голос"));
    expect(screen.getByRole("button", { name: "Iris · спокойный голос" })).toHaveAttribute("aria-expanded", "false");
  });
});
