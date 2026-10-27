// @vitest-environment jsdom
import React from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { LensButton } from "./DesignPack";
import { MaterialButton } from "../components/MaterialButton";
import { CustomSelect } from "../components/CustomSelect";

const feedback = vi.hoisted(() => ({
  reduced: false,
  transitions: [] as Array<{ target: HTMLElement; values: Record<string, unknown> }>,
  motions: [] as Array<{ target: HTMLElement; x: ReturnType<typeof vi.fn>; y: ReturnType<typeof vi.fn>;
    rotateX: ReturnType<typeof vi.fn>; rotateY: ReturnType<typeof vi.fn>; revert: ReturnType<typeof vi.fn> }>,
}));
vi.mock("../animations/core", () => ({
  isTestEnvironment: () => true,
  runSafeAnimation: () => ({ cancel: vi.fn() }),
  prefersReducedMotion: () => feedback.reduced,
  animate: (target: HTMLElement, values: Record<string, unknown>) => {
    feedback.transitions.push({ target, values });
    return { cancel: vi.fn() };
  },
}));
vi.mock("animejs", async (original) => ({
  ...await original<typeof import("animejs")>(),
  createAnimatable: (target: HTMLElement) => {
    const motion = { target, x: vi.fn(), y: vi.fn(), rotateX: vi.fn(), rotateY: vi.fn(), revert: vi.fn() };
    feedback.motions.push(motion);
    return motion;
  },
}));

beforeEach(() => {
  feedback.reduced = false;
  feedback.motions.length = 0;
  feedback.transitions.length = 0;
  vi.useFakeTimers();
  vi.stubGlobal("PointerEvent", MouseEvent);
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => window.setTimeout(() => callback(0), 16));
  vi.stubGlobal("cancelAnimationFrame", (id: number) => window.clearTimeout(id));
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); });

function button() {
  const element = screen.getByRole("button");
  vi.spyOn(element, "getBoundingClientRect").mockReturnValue({ left: 100, top: 100, width: 200, height: 50 } as DOMRect);
  return element;
}
function pointer(element: HTMLElement, type: "pointerenter" | "pointermove", x = 280, y = 110, pointerType = "mouse") {
  const event = new MouseEvent(type, { clientX: x, clientY: y });
  Object.defineProperty(event, "pointerType", { value: pointerType });
  fireEvent(element, event);
}

it("follows both pointer axes without moving the hit target, then returns on leave", () => {
  render(<LensButton>Кнопка</LensButton>);
  const element = button();
  pointer(element, "pointerenter");
  vi.advanceTimersByTime(20);
  const [face, light] = feedback.motions;
  expect(face.target).toBe(element.querySelector(".dp-hover-surface"));
  expect(face.rotateY.mock.lastCall?.[0]).toBeGreaterThan(0);
  expect(light.x.mock.lastCall?.[0]).toBeGreaterThan(0);
  pointer(element, "pointermove", 120, 140);
  vi.advanceTimersByTime(20);
  expect(face.rotateY.mock.lastCall?.[0]).toBeLessThan(0);
  expect(face.rotateX.mock.lastCall?.[0]).toBeLessThan(0);
  expect(light.x.mock.lastCall?.[0]).toBeLessThan(0);
  fireEvent.pointerLeave(element);
  expect(face.rotateY.mock.lastCall?.[0]).toBe(0);
  expect(light.x.mock.lastCall?.[0]).toBe(0);
});

it("excludes touch, disabled and reduced-motion buttons from cursor tracking", () => {
  const view = render(<LensButton>Кнопка</LensButton>);
  pointer(button(), "pointerenter", 280, 110, "touch");
  vi.advanceTimersByTime(20);
  expect(feedback.motions).toHaveLength(0);
  view.rerender(<LensButton disabled>Кнопка</LensButton>);
  pointer(button(), "pointerenter");
  vi.advanceTimersByTime(20);
  expect(feedback.motions).toHaveLength(0);
  feedback.reduced = true;
  view.rerender(<LensButton>Кнопка</LensButton>);
  pointer(button(), "pointerenter");
  vi.advanceTimersByTime(20);
  expect(feedback.motions).toHaveLength(0);
});

it("cancels queued movement and reverts active effects when disabled or unmounted", () => {
  const view = render(<LensButton seed={42}>Кнопка</LensButton>);
  pointer(button(), "pointerenter");
  view.rerender(<LensButton seed={42} disabled>Кнопка</LensButton>);
  vi.advanceTimersByTime(20);
  expect(feedback.motions).toHaveLength(0);
  view.rerender(<LensButton seed={42}>Кнопка</LensButton>);
  pointer(button(), "pointerenter");
  vi.advanceTimersByTime(20);
  view.unmount();
  expect(feedback.motions).toHaveLength(2);
  for (const motion of feedback.motions) expect(motion.revert).toHaveBeenCalledOnce();
});

it("presses only the application's decorative face and restores a quiet control on leave", () => {
  render(<MaterialButton materialKey="toolbar.microphone" appearance="quiet">Микрофон</MaterialButton>);
  const element = button();
  const face = element.querySelector<HTMLElement>(".dp-hover-surface")!;
  pointer(element, "pointerenter");
  fireEvent.pointerDown(element);
  expect(feedback.transitions.filter(change => change.target === face).slice(-1)[0]?.values).toMatchObject({ opacity: 1, scale: .96 });
  expect(feedback.transitions.some(change => change.target === element)).toBe(false);
  fireEvent.pointerLeave(element);
  expect(feedback.transitions.filter(change => change.target === face).slice(-1)[0]?.values).toMatchObject({ opacity: 0, scale: 1 });
});

it("reveals a quiet control while pressed without requiring pointer hover", () => {
  render(<MaterialButton materialKey="chrome.close" appearance="quiet" tone="danger">Закрыть</MaterialButton>);
  const element = button();
  const face = element.querySelector<HTMLElement>(".dp-hover-surface")!;
  fireEvent.pointerDown(element);
  expect(feedback.transitions.filter(change => change.target === face).slice(-1)[0]?.values).toMatchObject({ opacity: 1, scale: .96 });
  fireEvent.pointerCancel(element);
  expect(feedback.transitions.filter(change => change.target === face).slice(-1)[0]?.values).toMatchObject({ opacity: 0, scale: 1 });
});

it("restores the selected material when a disabled quiet control becomes active", () => {
  const view = render(<MaterialButton materialKey="navigation.test" className="navigation-button" disabled>Раздел</MaterialButton>);
  const face = screen.getByRole("button").querySelector<HTMLElement>(".dp-hover-surface")!;
  expect(face.style.opacity).toBe("0");
  view.rerender(<MaterialButton materialKey="navigation.test" className="navigation-button is-active">Раздел</MaterialButton>);
  expect(face.style.opacity).not.toBe("0");
});

it("keeps hover feedback when an open disclosure returns to its quiet state under the pointer", () => {
  const view = render(<MaterialButton materialKey="disclosure.hover" appearance="lens">Параметры</MaterialButton>);
  const element = button();
  vi.spyOn(element, "matches").mockImplementation(selector => selector === ":hover");
  view.rerender(<MaterialButton materialKey="disclosure.hover" appearance="quiet">Параметры</MaterialButton>);
  const face = element.querySelector<HTMLElement>(".dp-hover-surface")!;
  expect(face.style.opacity).toBe("1");
  fireEvent.pointerLeave(element);
  expect(feedback.transitions.filter(change => change.target === face).slice(-1)[0]?.values).toMatchObject({ opacity: 0 });
});

it("keeps a restrained reflection stable for the same button seed across remounts", () => {
  const reflection = (seed: number) => {
    const view = render(<MaterialButton materialKey="reflection.test" seed={seed}>Кнопка</MaterialButton>);
    const element = button();
    pointer(element, "pointerenter");
    const sheen = element.querySelector<HTMLElement>(".dp-hover-sheen")!;
    const changes = feedback.transitions.filter(change => change.target === sheen);
    const values = changes[changes.length - 1].values;
    const result = { values, angle: sheen.style.getPropertyValue("--dp-sheen-angle"), spread: sheen.style.getPropertyValue("--dp-sheen-spread") };
    expect((values.opacity as number[])[1]).toBeLessThan(.5);
    view.unmount();
    return result;
  };
  const first = reflection(42);
  expect(reflection(42)).toEqual(first);
  expect(reflection(73)).not.toEqual(first);
});

it("keeps a fixed surface aligned on hover and press while its light follows the pointer", () => {
  render(<MaterialButton materialKey="shortcuts.bind.search" appearance="quiet" surfaceMotion={false}>Ctrl + K</MaterialButton>);
  const element = button();
  const face = element.querySelector<HTMLElement>(".dp-hover-surface")!;
  pointer(element, "pointerenter");
  vi.advanceTimersByTime(20);
  expect(feedback.motions).toHaveLength(1);
  const light = feedback.motions[0];
  expect(light.target).toBe(element.querySelector(".dp-hover-spot"));
  expect(light.x.mock.lastCall?.[0]).toBeGreaterThan(0);
  pointer(element, "pointermove", 120, 140);
  vi.advanceTimersByTime(20);
  expect(light.x.mock.lastCall?.[0]).toBeLessThan(0);
  fireEvent.pointerDown(element);
  expect(feedback.transitions.filter(change => change.target === face).slice(-1)[0]?.values).toMatchObject({ opacity: 1 });
  fireEvent.pointerUp(element);
  for (const key of ["Enter", " "]) {
    fireEvent.keyDown(element, { key });
    fireEvent.keyUp(element, { key });
  }
  fireEvent.pointerLeave(element);
  expect(feedback.transitions.filter(change => change.target === face).slice(-1)[0]?.values).toMatchObject({ opacity: 0 });
  expect(feedback.transitions.some(change => "scale" in change.values)).toBe(false);
});

it("keeps dropdown options at full size on pointer and keyboard presses while retaining light feedback", () => {
  render(<CustomSelect value="one"><option value="one">Один на один</option><option value="group">Несколько собеседников</option></CustomSelect>);
  fireEvent.click(screen.getByRole("button"));
  const row = within(screen.getByRole("listbox")).getByRole("option", { name: "Один на один" });
  const light = row.querySelector<HTMLElement>(".dp-hover-light")!;
  feedback.transitions.length = 0;
  fireEvent.pointerDown(row);
  expect(feedback.transitions.filter(change => change.target === light).slice(-1)[0]?.values).toMatchObject({ opacity: 1 });
  fireEvent.pointerUp(row);
  fireEvent.pointerDown(row);
  fireEvent.pointerCancel(row);
  for (const key of ["Enter", " "]) {
    fireEvent.keyDown(row, { key });
    fireEvent.keyUp(row, { key });
  }
  expect(feedback.transitions.length).toBeGreaterThan(0);
  expect(feedback.transitions.some(change => "scale" in change.values)).toBe(false);
});
