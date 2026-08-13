// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach } from "vitest";
import { createElement } from "react";

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
