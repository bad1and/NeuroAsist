// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { describe, expect, it } from "vitest";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach } from "vitest";
import { createElement } from "react";
import { createPortal } from "react-dom";

import { translateInterfaceText, useInterfaceLocale } from "./i18n";
import type { InterfaceLocale } from "./types";

afterEach(() => cleanup());

function TranslationFixture({ locale }: { locale: InterfaceLocale }) {
  useInterfaceLocale(locale);
  return createElement("div", undefined,
    createElement("span", undefined, "Сбалансированная"),
    createElement("span", undefined, "Сбалансированное"),
  );
}

describe("interface translations", () => {
  it("localizes portals beside the real root, including newly opened content, without touching user text", async () => {
    const root = document.createElement("div");
    root.id = "root"; document.body.append(root);
    function PortalFixture({ locale, open }: { locale: InterfaceLocale; open: boolean }) {
      useInterfaceLocale(locale);
      return createElement("section", null, "Настройки", open && createPortal(createElement("aside", null,
        createElement("strong", null, "Подготовить первый разговор"),
        createElement("input", { placeholder: "Поиск по памяти" }),
        createElement("p", { "data-i18n-skip": true }, "Настройки — пользовательский текст"),
        createElement("pre", null, "Настройки")), document.body));
    }
    const view = render(createElement(PortalFixture, { locale: "en", open: false }), { container: root });
    expect(screen.getByText("Settings")).toBeInTheDocument();
    view.rerender(createElement(PortalFixture, { locale: "en", open: true }));
    await waitFor(() => expect(screen.getByText("Prepare your first conversation")).toBeInTheDocument());
    expect(screen.getByPlaceholderText("Search memory")).toBeInTheDocument();
    expect(screen.getByText("Настройки — пользовательский текст")).toBeInTheDocument();
    await act(async () => view.rerender(createElement(PortalFixture, { locale: "ru", open: true })));
    expect(screen.getByText("Подготовить первый разговор")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Поиск по памяти")).toBeInTheDocument();
    view.unmount(); root.remove();
  });
  it("translates model and backup actions and empty states", () => {
    expect(translateInterfaceText("Скачать", "en")).toBe("Download");
    expect(translateInterfaceText("Восстановить", "en")).toBe("Restore");
    expect(translateInterfaceText("Резервных копий пока нет", "en")).toBe("No backups yet");
    expect(translateInterfaceText("Окружение и гео", "en")).toBe("Environment & location");
  });
  it("translates interface copy in both directions", () => {
    expect(translateInterfaceText("Настройки", "en")).toBe("Settings");
    expect(translateInterfaceText("Application language", "ru")).toBe("Язык приложения");
    expect(translateInterfaceText("Естественное", "en")).toBe("Natural");
    expect(translateInterfaceText("начальное", "en")).toBe("Initial");
    expect(translateInterfaceText("спокойная", "en")).toBe("Calm");
    expect(translateInterfaceText("Начните разговор", "en")).toBe("Start a conversation");
    expect(translateInterfaceText("Сохранено", "en")).toBe("Saved");
    expect(translateInterfaceText("Перезапустите Iris, чтобы использовать модель.", "en"))
      .toBe("Restart Iris to use this model.");
    expect(translateInterfaceText("Начать новый диалог", "en")).toBe("Start new chat");
    expect(translateInterfaceText("Все сообщения и сводки текущего диалога будут удалены без возможности восстановления. Долгосрочная память Iris останется.", "en"))
      .toBe("All messages and summaries in the current chat will be deleted permanently. Iris's long-term memory will remain.");
    expect(translateInterfaceText("Обновить среду", "en")).toBe("Refresh environment");
    expect(translateInterfaceText("Logs, commands, and errors", "ru")).toBe("Логи, команды и ошибки");
    expect(translateInterfaceText("Planning step 3", "ru")).toBe("Шаг планирования 3");
    expect(translateInterfaceText("Задачи кодинг-агента", "en")).toBe("Coding Agent tasks");
    expect(translateInterfaceText("Песочница и окружение Docker", "en")).toBe("Docker sandbox and environment");
    expect(translateInterfaceText("Параметры кодинг-агента", "en")).toBe("Coding Agent settings");
    expect(translateInterfaceText("Режим разработчика", "en")).toBe("Developer mode");
    expect(translateInterfaceText(
      "Разблокирует расширенные настройки голоса, таймингов живого разговора, отладки аватара и прямого управления данными.",
      "en",
    )).toBe("Unlocks advanced settings for voice, live-conversation timing, avatar debugging, and direct data control.");
    expect(translateInterfaceText("Сначала новые", "en")).toBe("Newest first");
    expect(translateInterfaceText("Целостность", "en")).toBe("Integrity");
    expect(translateInterfaceText("Живая история", "en")).toBe("Live history");
    expect(translateInterfaceText("Что влияет на настроение", "en")).toBe("What affects the mood");
    expect(translateInterfaceText("Шутка / Подкол", "en")).toBe("Joke / Teasing");
    expect(translateInterfaceText("Влияет сейчас", "en")).toBe("Active now");
    expect(translateInterfaceText("Сегодня в 11:53 PM", "en")).toBe("Today at 11:53 PM");
    expect(translateInterfaceText("Docker daemon готов к запуску контейнеров", "en"))
      .toBe("Docker daemon is ready to start containers");
  });

  it("restores the original Russian grammatical form after switching back", () => {
    const { rerender } = render(createElement(TranslationFixture, { locale: "en" }));
    expect(screen.getAllByText("Balanced")).toHaveLength(2);

    rerender(createElement(TranslationFixture, { locale: "ru" }));
    expect(screen.getByText("Сбалансированная")).toBeInTheDocument();
    expect(screen.getByText("Сбалансированное")).toBeInTheDocument();
  });

  it("does not alter text that is not interface copy", () => {
    expect(translateInterfaceText("Неприкосновенная пользовательская фраза", "en"))
      .toBe("Неприкосновенная пользовательская фраза");
  });
});
