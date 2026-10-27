// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { Disclosure } from "./Disclosure";

afterEach(cleanup);

it("keeps an unsaved field mounted and returns focus when its panel closes", () => {
  render(<Disclosure materialKey="test.fields" label="Параметры" regionLabel="Параметры формы"><input aria-label="Черновик" defaultValue="" /></Disclosure>);
  const trigger = screen.getByRole("button", { name: "Параметры" });
  expect(screen.queryByRole("region", { name: "Параметры формы" })).toBeNull();
  fireEvent.click(trigger);
  const input = screen.getByRole("textbox", { name: "Черновик" });
  fireEvent.change(input, { target: { value: "не сохранено" } });
  input.focus();
  fireEvent.click(trigger);
  expect(trigger).toHaveFocus();
  expect(document.getElementById(trigger.getAttribute("aria-controls")!)).toHaveAttribute("inert");
  fireEvent.click(trigger);
  expect(screen.getByRole("textbox", { name: "Черновик" })).toBe(input);
  expect(input).toHaveValue("не сохранено");
});

it("supports externally revealing and closing a section without changing its controlled value", () => {
  const change = vi.fn();
  const view = (open: boolean) => <Disclosure materialKey="test.controlled" label="Журнал" open={open} onOpenChange={change}><p>Запросы</p></Disclosure>;
  const result = render(view(false));
  result.rerender(view(true));
  const trigger = screen.getByRole("button", { name: "Журнал" });
  expect(screen.getByText("Запросы")).toBeVisible();
  fireEvent.click(trigger);
  expect(change).toHaveBeenCalledWith(false);
  expect(trigger).toHaveAttribute("aria-expanded", "true");
  result.rerender(view(false));
  expect(screen.getByText("Запросы")).not.toBeVisible();
});

it("keeps nested panels independent, initially open content, and unique control links", () => {
  render(<Disclosure materialKey="test.outer" label="Документ" defaultOpen>
    <Disclosure materialKey="test.inner" label="Фрагмент"><p>Текст фрагмента</p></Disclosure>
  </Disclosure>);
  const outer = screen.getByRole("button", { name: "Документ" });
  const inner = screen.getByRole("button", { name: "Фрагмент" });
  expect(outer.getAttribute("aria-controls")).not.toBe(inner.getAttribute("aria-controls"));
  fireEvent.click(inner);
  expect(screen.getByText("Текст фрагмента")).toBeVisible();
  fireEvent.click(outer);
  fireEvent.click(outer);
  expect(inner).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByText("Текст фрагмента")).toBeVisible();
});

it("places header actions outside the trigger and does not toggle when they are used", () => {
  const action = vi.fn();
  render(<Disclosure materialKey="test.actions" label="Диагностика" actions={<button onClick={action}>DEV</button>}><p>Метрики</p></Disclosure>);
  const trigger = screen.getByRole("button", { name: "Диагностика" });
  expect(within(trigger).queryByRole("button")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "DEV" }));
  expect(action).toHaveBeenCalledOnce();
  expect(trigger).toHaveAttribute("aria-expanded", "false");
});

it("respects the host section being hidden without resetting an open panel", () => {
  const view = (hidden: boolean) => <Disclosure hidden={hidden} materialKey="test.hidden" label="Технические данные" defaultOpen><p>Система</p></Disclosure>;
  const result = render(view(true));
  expect(screen.queryByRole("button", { name: "Технические данные" })).toBeNull();
  result.rerender(view(false));
  expect(screen.getByRole("button", { name: "Технические данные" })).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByText("Система")).toBeVisible();
});
