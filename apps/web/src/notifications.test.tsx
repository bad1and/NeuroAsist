// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, act } from "@testing-library/react";
import React from "react";
import { notify, notificationStore, notifyBackendEvent } from "./notifications";
import type { BackendEvent } from "./types";
import { NotificationHost } from "./components/NotificationHost";
import * as animations from "./animations";

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
    it("keeps avatar dispatch diagnostics out of toasts while showing playback failures", () => {
      const event = { id: "delivery", type: "avatar.command_failed", level: "warning", message: "Avatar command dispatched", metadata: {}, created_at: "2026-10-01T00:00:00Z" } as BackendEvent;
      notifyBackendEvent(event);
      notify.warning("Предупреждение: avatar.command_failed", event.message);
      notify.warning("Предупреждение: avatar.command_ошибка", event.message);
      expect(notificationStore.getSnapshot()).toHaveLength(0);
      notifyBackendEvent({ ...event, type: "avatar.playback.failed", message: "WAV playback failed" });
      expect(notificationStore.getSnapshot()).toHaveLength(1);
      expect(notificationStore.getSnapshot()[0].message).toBe("WAV playback failed");
    });

    it("ignores a legacy avatar warning synchronized from another window", () => {
      const previousChannel = globalThis.BroadcastChannel;
      let receive: ((event: { data: unknown }) => void) | null = null;
      class TestChannel {
        set onmessage(callback: (event: { data: unknown }) => void) { receive = callback; }
        postMessage() {}
      }
      vi.stubGlobal("BroadcastChannel", TestChannel);
      try {
        const Store = notificationStore.constructor as new () => typeof notificationStore;
        const store = new Store();
        const oldWarning = { id: "old-warning", type: "warning", title: "Предупреждение: avatar.command_failed", message: "Avatar command dispatched", createdAt: 1 };
        receive!({ data: { type: "show", notification: oldWarning } });
        expect(store.getSnapshot()).toHaveLength(0);
        receive!({ data: { type: "show", notification: { ...oldWarning, title: "Другая ошибка" } } });
        expect(store.getSnapshot()).toHaveLength(1);
      } finally { vi.stubGlobal("BroadcastChannel", previousChannel); }
    });
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
    it("uses shared entrance and waits for the shared exit before removing a toast", () => {
      let finishExit: (() => void) | undefined;
      const motion = vi.spyOn(animations, "animateNotification").mockImplementation((_card, phase, finish) => {
        if (phase === "exit") finishExit = finish;
        return { cancel: vi.fn() } as unknown as animations.Animation;
      });
      try {
        act(() => { notify.info("Анимация", "Проверка", { duration: "persistent" }); });
        render(<NotificationHost />);
        expect(motion.mock.calls[0][1]).toBe("enter");
        fireEvent.click(screen.getByRole("button", { name: "Закрыть уведомление" }));
        expect(motion.mock.calls[1][1]).toBe("exit");
        expect(screen.getByText("Анимация")).toBeInTheDocument();
        act(() => finishExit?.());
        expect(screen.queryByText("Анимация")).toBeNull();
      } finally { motion.mockRestore(); }
    });
    it("keeps the conversation slot above notifications after timers and dismiss-all", () => {
      const pinnedContentRef = React.createRef<HTMLDivElement>();
      render(<NotificationHost pinnedContentRef={pinnedContentRef} />);
      const conversation = document.createElement("div");
      conversation.textContent = "Разговор продолжается";
      pinnedContentRef.current!.appendChild(conversation);
      act(() => { notify.info("Новое уведомление", "Сообщение"); });
      const host = screen.getByRole("complementary", { name: "Уведомления приложения" });
      expect(host.firstElementChild).toBe(pinnedContentRef.current);
      act(() => { vi.advanceTimersByTime(5000); });
      expect(screen.getByText("Разговор продолжается")).toBeVisible();
      act(() => { notify.dismissAll(); });
      expect(host.firstElementChild).toContainElement(conversation);
    });
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

    it("renders determinate task progress for a persistent startup notification", () => {
      act(() => {
        notify.info("Подготавливаю микрофон", "Загружаю голосовые сервисы · 36%", {
          id: "voice-microphone-startup",
          duration: "persistent",
          progress: 0.36,
        });
      });

      render(<NotificationHost />);

      const progress = screen.getByRole("progressbar", { name: "Прогресс" });
      expect(progress).toHaveAttribute("aria-valuenow", "36");
      expect(progress.querySelector("span")).toHaveStyle({ width: "36%" });
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
