// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { describe, expect, it, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
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
