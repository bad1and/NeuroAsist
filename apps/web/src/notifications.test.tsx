// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, act } from "@testing-library/react";
import React from "react";
import { notify, notificationStore } from "./notifications";
import { NotificationHost } from "./components/NotificationHost";

describe("Unified Notification System", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    notify.dismissAll();
  });

  afterEach(() => {
    act(() => {
      notify.dismissAll();
    });
    vi.clearAllTimers();
    vi.useRealTimers();
    cleanup();
  });

  describe("notificationStore / notify helper", () => {
    it("adds and dismisses notifications with appropriate default durations", () => {
      const errorId = notify.error("Ошибка сети", "Не удалось связаться с сервером");
      const notifs = notificationStore.getSnapshot();
      expect(notifs).toHaveLength(1);
      expect(notifs[0].id).toBe(errorId);
      expect(notifs[0].type).toBe("error");
      expect(notifs[0].duration).toBe("persistent");

      const successId = notify.success("Успех", "Сохранено");
      const updated = notificationStore.getSnapshot();
      expect(updated).toHaveLength(2);
      expect(updated[0].id).toBe(successId);
      expect(updated[0].duration).toBe(4500);

      notify.dismiss(errorId);
      expect(notificationStore.getSnapshot()).toHaveLength(1);
      expect(notificationStore.getSnapshot()[0].id).toBe(successId);
    });

    it("prevents duplicates by moving existing matching notification to front", () => {
      notify.info("Тест", "Одинаковое сообщение");
      notify.warning("Другое", "Сообщение");
      expect(notificationStore.getSnapshot()).toHaveLength(2);

      notify.info("Тест", "Одинаковое сообщение");
      expect(notificationStore.getSnapshot()).toHaveLength(2);
      expect(notificationStore.getSnapshot()[0].title).toBe("Тест");
    });
  });

  describe("NotificationHost component", () => {
    it("renders nothing when there are no notifications", () => {
      const { container } = render(<NotificationHost />);
      expect(container.firstChild).toBeNull();
    });

    it("renders active notification with title, message and icon", () => {
      act(() => {
        notify.info("Память", "Сохранено: Любимый жанр.");
      });

      render(<NotificationHost />);

      expect(screen.getByText("Память")).toBeInTheDocument();
      expect(screen.getByText("Сохранено: Любимый жанр.")).toBeInTheDocument();
      expect(screen.getByRole("status")).toBeInTheDocument();
    });

    it("renders and handles action button click", () => {
      const actionFn = vi.fn();
      act(() => {
        notify.reminder("Напоминание", "Планы на день", {
          actions: [{ label: "Открыть", onClick: actionFn, variant: "primary" }],
        });
      });

      render(<NotificationHost />);

      const actionBtn = screen.getByRole("button", { name: "Открыть" });
      expect(actionBtn).toBeInTheDocument();

      fireEvent.click(actionBtn);
      expect(actionFn).toHaveBeenCalledTimes(1);
    });

    it("toggles expanded state for details", () => {
      act(() => {
        notify.error("Критическая ошибка", "Произошла ошибка при выполнении операции", {
          details: "Error: Connection refused\n  at WebSocket.connect",
        });
      });

      render(<NotificationHost />);

      const expandBtn = screen.getByLabelText("Развернуть подробности");
      expect(expandBtn).toBeInTheDocument();
      expect(screen.queryByText(/Connection refused/)).not.toBeInTheDocument();

      fireEvent.click(expandBtn);
      expect(screen.getByText(/Connection refused/)).toBeInTheDocument();

      const collapseBtn = screen.getByLabelText("Свернуть подробности");
      fireEvent.click(collapseBtn);
      expect(screen.queryByText(/Connection refused/)).not.toBeInTheDocument();
    });

    it("shows multiple notifications simultaneously and allows dismiss", () => {
      act(() => {
        notify.info("Первое", "Сообщение 1");
        notify.warning("Второе", "Сообщение 2");
      });

      render(<NotificationHost />);

      // Both notifications should now be visible simultaneously!
      expect(screen.getByText("Первое")).toBeInTheDocument();
      expect(screen.getByText("Второе")).toBeInTheDocument();

      // Close first visible notification
      const closeBtns = screen.getAllByLabelText("Закрыть уведомление");
      fireEvent.click(closeBtns[0]);

      act(() => {
        vi.advanceTimersByTime(250);
      });

      // Remaining notification should still be visible
      expect(screen.getByText("Первое")).toBeInTheDocument();
    });

    it("shows queue badge when notifications exceed maxVisible", () => {
      act(() => {
        notify.info("1", "Сообщение 1");
        notify.info("2", "Сообщение 2");
        notify.info("3", "Сообщение 3");
        notify.info("4", "Сообщение 4");
      });

      render(<NotificationHost maxVisible={3} />);
      expect(screen.getByText("+1")).toBeInTheDocument();
    });

    it("calls onNavigate when clicking clickable notification", () => {
      const navigateFn = vi.fn();
      act(() => {
        notify.info("Память", "Новая запись", { navigateView: "memory" });
      });

      render(<NotificationHost onNavigate={navigateFn} />);

      const card = screen.getByRole("status");
      fireEvent.click(card);

      expect(navigateFn).toHaveBeenCalledWith("memory");
    });

    it("copies error details to clipboard when clicking copy button on error notification", async () => {
      const writeTextMock = vi.fn().mockResolvedValue(undefined);
      Object.assign(navigator, {
        clipboard: {
          writeText: writeTextMock,
        },
      });

      act(() => {
        notify.error("Сбой сервиса", "Не удалось запустить ядро", {
          details: "RuntimeError: Connection timed out",
        });
      });

      render(<NotificationHost />);

      const copyBtn = screen.getByRole("button", { name: /Скопировать/i });
      expect(copyBtn).toBeInTheDocument();

      fireEvent.click(copyBtn);

      expect(writeTextMock).toHaveBeenCalledWith(
        expect.stringContaining("RuntimeError: Connection timed out")
      );
      expect(screen.getByText("Скопировано!")).toBeInTheDocument();
    });
  });
});

