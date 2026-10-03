// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { describe, expect, it, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, within } from "@testing-library/react";
import React, { useState } from "react";
import { CustomSelect } from "./CustomSelect";

describe("CustomSelect", () => {
  afterEach(() => {
    cleanup();
  });

  it("отображает текущее выбранное значение на кнопке", () => {
    render(
      <CustomSelect value="one_to_one">
        <option value="one_to_one">Один на один</option>
        <option value="group">Несколько собеседников</option>
      </CustomSelect>
    );

    expect(screen.getByRole("button", { name: "Один на один" })).toBeInTheDocument();
  });

  it("открывает кастомный список при клике на кнопку и закрывает при повторном клике", () => {
    render(
      <CustomSelect value="one_to_one">
        <option value="one_to_one">Один на один</option>
        <option value="group">Несколько собеседников</option>
      </CustomSelect>
    );

    const trigger = screen.getByRole("button", { name: "Один на один" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    // Клик для открытия
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("listbox")).toBeInTheDocument();

    // Клик для закрытия
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("вызывает onChange при выборе опции и закрывает список", () => {
    const handleChange = vi.fn();
    render(
      <CustomSelect value="one_to_one" onChange={handleChange}>
        <option value="one_to_one">Один на один</option>
        <option value="group">Несколько собеседников</option>
      </CustomSelect>
    );

    const trigger = screen.getByRole("button", { name: "Один на один" });
    fireEvent.click(trigger);

    const listbox = screen.getByRole("listbox");
    const option = listbox.querySelector(".custom-select-option:not(.selected)") as HTMLElement;
    expect(option).toBeInTheDocument();
    expect(option.textContent).toBe("Несколько собеседников");

    fireEvent.click(option);
    expect(handleChange).toHaveBeenCalledWith({ target: { value: "group" } });
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("поддерживает навигацию с клавиатуры (Escape, стрелки, Enter)", () => {
    const handleChange = vi.fn();
    const { container } = render(
      <CustomSelect value="one_to_one" onChange={handleChange}>
        <option value="one_to_one">Один на один</option>
        <option value="group">Несколько собеседников</option>
      </CustomSelect>
    );

    const selectContainer = container.querySelector(".custom-select-container") as HTMLElement;

    // Открытие стрелкой вниз
    fireEvent.keyDown(selectContainer, { key: "ArrowDown" });
    expect(screen.getByRole("listbox")).toBeInTheDocument();

    // Перемещение к следующему пункту
    fireEvent.keyDown(selectContainer, { key: "ArrowDown" });

    // Выбор через Enter
    fireEvent.keyDown(selectContainer, { key: "Enter" });
    expect(handleChange).toHaveBeenCalledWith({ target: { value: "group" } });
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();

    // Проверка Escape
    fireEvent.keyDown(selectContainer, { key: "ArrowDown" });
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    fireEvent.keyDown(selectContainer, { key: "Escape" });
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("выбранный элемент имеет класс .selected и не содержит символа галочки ✓ в тексте", () => {
    render(
      <CustomSelect value="one_to_one">
        <option value="one_to_one">Один на один</option>
        <option value="group">Несколько собеседников</option>
      </CustomSelect>
    );

    fireEvent.click(screen.getByRole("button", { name: "Один на один" }));
    const selectedItem = screen.getByRole("listbox").querySelector(".custom-select-option.selected") as HTMLElement;

    expect(selectedItem).toBeInTheDocument();
    expect(selectedItem.textContent).toBe("Один на один");
    expect(selectedItem.textContent).not.toContain("✓");
  });

  it("Home и End выбирают доступные края списка, пропуская недоступные пункты", () => {
    const onChange = vi.fn();
    render(<CustomSelect value="middle" onChange={onChange}>
      <option value="disabled-first" disabled>Недоступное начало</option>
      <option value="first">Первый</option>
      <option value="middle">Середина</option>
      <option value="last">Последний</option>
      <option value="disabled-last" disabled>Недоступный конец</option>
    </CustomSelect>);
    const trigger = screen.getByRole("button", { name: "Середина" });
    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    const list = screen.getByRole("listbox");
    expect(trigger).toHaveAttribute("aria-controls", list.id);
    expect(list).toHaveAttribute("aria-labelledby", trigger.id);
    fireEvent.keyDown(trigger, { key: "End" });
    expect(within(list).getByRole("option", { name: "Последний" })).toHaveClass("highlighted");
    expect(within(list).getByRole("option", { name: "Середина" })).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(trigger, { key: "Home" });
    fireEvent.keyDown(trigger, { key: "Enter" });
    expect(onChange).toHaveBeenCalledWith({ target: { value: "first" } });
    expect(document.activeElement).toBe(trigger);
  });

  it("не позволяет выбрать недоступный пункт мышью или при отсутствии доступных вариантов", () => {
    const onChange = vi.fn();
    render(<CustomSelect value="disabled" onChange={onChange}>
      <option value="disabled" disabled>Недоступно</option>
    </CustomSelect>);
    const trigger = screen.getByRole("button", { name: "Недоступно" });
    fireEvent.click(trigger);
    const option = within(screen.getByRole("listbox")).getByRole("option", { name: "Недоступно" });
    expect(option).toHaveAttribute("aria-disabled", "true");
    fireEvent.mouseEnter(option);
    fireEvent.click(option);
    fireEvent.keyDown(trigger, { key: "Home" });
    fireEvent.keyDown(trigger, { key: "End" });
    fireEvent.keyDown(trigger, { key: "Enter" });
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    fireEvent.mouseDown(document.body);
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("раскрывает объединённую поверхность вверх у нижнего края окна", () => {
    const { container } = render(<CustomSelect value="one">
      <option value="one">Первый</option><option value="two">Второй</option>
    </CustomSelect>);
    const root = container.querySelector<HTMLElement>(".custom-select-container")!;
    const trigger = screen.getByRole("button", { name: "Первый" });
    vi.spyOn(trigger, "getBoundingClientRect").mockReturnValue({
      top: window.innerHeight - 50, bottom: window.innerHeight - 12,
      height: 38, width: 300, left: 0, right: 300, x: 0, y: window.innerHeight - 50, toJSON: () => ({}),
    });
    fireEvent.click(trigger);
    expect(root).toHaveAttribute("data-placement", "top");
    fireEvent.keyDown(root, { key: "Escape" });
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("закрывает меню, если открытое поле становится недоступным", () => {
    const { rerender } = render(<CustomSelect value="one"><option value="one">Первый</option></CustomSelect>);
    fireEvent.click(screen.getByRole("button", { name: "Первый" }));
    rerender(<CustomSelect value="one" disabled><option value="one">Первый</option></CustomSelect>);
    expect(screen.queryByRole("listbox")).toBeNull();
    expect(screen.getByRole("button", { name: "Первый" })).toBeDisabled();
  });

  it("скрытый нативный select синхронизируется и доступен для автоматических тестов", () => {
    function ControlledTest() {
      const [val, setVal] = useState("one_to_one");
      return (
        <label>
          Участники
          <CustomSelect value={val} onChange={(e) => setVal(e.target.value)}>
            <option value="one_to_one">Один на один</option>
            <option value="group">Несколько собеседников</option>
          </CustomSelect>
        </label>
      );
    }

    render(<ControlledTest />);
    const nativeSelect = screen.getByLabelText("Участники");
    expect(nativeSelect).toHaveValue("one_to_one");

    fireEvent.change(nativeSelect, { target: { value: "group" } });
    expect(nativeSelect).toHaveValue("group");
    expect(screen.getByRole("button", { name: "Несколько собеседников" })).toBeInTheDocument();
  });
});
