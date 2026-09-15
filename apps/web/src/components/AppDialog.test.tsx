// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, act } from "@testing-library/react";
import React from "react";
import { AppDialog } from "./AppDialog";

describe("AppDialog (Top Notification Format)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.clearAllTimers();
    vi.useRealTimers();
    cleanup();
  });

  it("не рендерит ничего, когда open=false", () => {
    const onClose = vi.fn();
    render(
      <AppDialog
        open={false}
        title="Тестовый диалог"
        description="Описание диалога"
        onClose={onClose}
      >
        <button type="button">Кнопка</button>
      </AppDialog>
    );

    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(screen.queryByText("Тестовый диалог")).not.toBeInTheDocument();
  });

  it("рендерит диалог в формате уведомления с заголовком и описанием при open=true", () => {
    const onClose = vi.fn();
    render(
      <AppDialog
        open={true}
        title="Начать новый диалог?"
        description="Текущий диалог будет завершён и сохранён в истории."
        onClose={onClose}
        variant="danger"
      >
        <div className="dialog-actions">
          <button className="secondary" type="button" onClick={onClose}>
            Отмена
          </button>
          <button className="danger-button" type="button">
            Начать
          </button>
        </div>
      </AppDialog>
    );

    const dialog = screen.getByRole("alertdialog");
    expect(dialog).toBeInTheDocument();
    expect(dialog).toHaveClass("notification-card");
    expect(dialog).toHaveClass("app-dialog-card");
    expect(dialog).toHaveClass("is-danger");

    expect(screen.getByRole("heading", { name: "Начать новый диалог?" })).toBeInTheDocument();
    expect(screen.getByText("Текущий диалог будет завершён и сохранён в истории.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Отмена" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Начать" })).toBeInTheDocument();
  });

  it("вызывает onClose по нажатию на кнопку закрытия (крестик) с плавной анимацией", () => {
    const onClose = vi.fn();
    render(
      <AppDialog
        open={true}
        title="Подтверждение"
        onClose={onClose}
      >
        <button type="button">ОК</button>
      </AppDialog>
    );

    const closeBtn = screen.getByRole("button", { name: "Закрыть диалог" });
    expect(closeBtn).toBeInTheDocument();

    fireEvent.click(closeBtn);

    // До истечения таймера анимации (190мс) onClose еще не вызвался, но выставлен класс is-exiting
    const dialog = screen.getByRole("alertdialog");
    expect(dialog).toHaveClass("is-exiting");
    expect(onClose).not.toHaveBeenCalled();

    // Перематываем таймер
    act(() => {
      vi.advanceTimersByTime(200);
    });

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("закрывает диалог по клавише Escape", () => {
    const onClose = vi.fn();
    render(
      <AppDialog
        open={true}
        title="Удалить запись?"
        onClose={onClose}
      >
        <button type="button">Удалить</button>
      </AppDialog>
    );

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("корректно рендерит форму с textarea внутри интерактивного диалога-уведомления", () => {
    const onClose = vi.fn();
    const onSave = vi.fn();
    render(
      <AppDialog
        open={true}
        title="Исправить запись памяти"
        description="Исправление будет закреплено."
        onClose={onClose}
        variant="info"
      >
        <label className="form-field">
          <span>Значение</span>
          <textarea defaultValue="Исходный текст" aria-label="Значение памяти" />
        </label>
        <div className="dialog-actions">
          <button className="secondary" type="button" onClick={onClose}>
            Отмена
          </button>
          <button type="button" onClick={onSave}>
            Сохранить
          </button>
        </div>
      </AppDialog>
    );

    const textarea = screen.getByLabelText("Значение памяти");
    expect(textarea).toBeInTheDocument();
    expect(textarea).toHaveValue("Исходный текст");

    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(onSave).toHaveBeenCalledTimes(1);
  });

  it("плавно анимирует выход с классом is-exiting при смене open с true на false (например, по нажатию Отмена)", () => {
    let isOpen = true;
    const { rerender } = render(
      <AppDialog
        open={isOpen}
        title="Диалог"
        description="Текст диалога"
        onClose={() => { isOpen = false; }}
      >
        <div className="dialog-actions">
          <button className="secondary" type="button" onClick={() => { isOpen = false; }}>
            Отмена
          </button>
        </div>
      </AppDialog>
    );

    expect(screen.getByRole("alertdialog")).toBeInTheDocument();

    // Симулируем клик на Отмена, который переключает open в false в родительском компоненте
    fireEvent.click(screen.getByRole("button", { name: "Отмена" }));
    rerender(
      <AppDialog
        open={false}
        title="Диалог"
        description="Текст диалога"
        onClose={() => {}}
      >
        <div className="dialog-actions">
          <button className="secondary" type="button">Отмена</button>
        </div>
      </AppDialog>
    );

    // Диалог всё ещё в DOM, но имеет класс is-exiting для плавной анимации вылета
    const dialog = screen.getByRole("alertdialog");
    expect(dialog).toBeInTheDocument();
    expect(dialog).toHaveClass("is-exiting");

    // По истечении 200мс диалог окончательно размонтируется
    act(() => {
      vi.advanceTimersByTime(200);
    });

    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });
});
