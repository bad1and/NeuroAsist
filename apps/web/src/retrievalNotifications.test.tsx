// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { notify, notificationStore } from "./notifications";
import { RetrievalNotifications } from "./retrievalNotifications";
import { NotificationHost } from "./components/NotificationHost";
import type { BackendEvent } from "./types";

const event = (phase: string, sequence = 1, turn = "a", extra = {}): BackendEvent => ({
  id: `${turn}-${sequence}`, type: "retrieval.progress", level: "info", message: "Search progress",
  created_at: new Date().toISOString(), metadata: { session_id: "s", turn_id: turn, generation: 1, phase, sequence, query: "Песня Альфа", ...extra },
});
beforeEach(() => notify.dismissAll());
afterEach(() => { cleanup(); notify.dismissAll(); });

describe("уведомления поиска", () => {
  it("по умолчанию молчит и не показывает завершённую историю", () => {
    const notices = new RetrievalNotifications();
    notices.consume(event("searching"));
    notices.setEnabled(true);
    notices.consume(event("reading", 2));
    notices.consume(event("finished", 3));
    notices.consume(event("finished", 1, "history"));
    expect(notificationStore.getSnapshot()).toHaveLength(0);
  });
  it("обновляет одно уведомление на месте и раскрывает источники", () => {
    const notices = new RetrievalNotifications(); notices.setEnabled(true);
    notices.consume(event("searching"));
    const id = notificationStore.getSnapshot()[0].id;
    notify.info("Другой процесс", "Уведомление");
    notices.consume(event("reading", 2));
    expect(notificationStore.getSnapshot()[0].title).toBe("Другой процесс");
    expect(notificationStore.getSnapshot()[1].id).toBe(id);
    notices.consume(event("finished", 3, "a", { status: "ok", evidence_status: "partial", latency_ms: 2100,
      sources: [{ title: "Исходный документ", url: "https://example.org/alpha" }] }));
    expect(notificationStore.getSnapshot()).toHaveLength(2);
    render(<NotificationHost />);
    fireEvent.click(screen.getByRole("button", { name: "Развернуть подробности" }));
    expect(screen.getByText(/Исходный документ/)).toHaveTextContent("https://example.org/alpha");
    expect(screen.getByText("Найдена часть информации")).toBeInTheDocument();
  });
  it("не возвращает закрытую карточку при следующем этапе или дубле", () => {
    const notices = new RetrievalNotifications(); notices.setEnabled(true);
    notices.consume(event("searching"));
    notify.dismiss(notificationStore.getSnapshot()[0].id);
    notices.consume(event("searching", 2));
    notices.consume(event("reading", 3));
    notices.consume(event("finished", 4));
    notices.consume(event("searching", 1));
    expect(notificationStore.getSnapshot()).toHaveLength(0);
  });
  it("игнорирует поздние этапы отменённого хода и очищает карточки при отключении", () => {
    const notices = new RetrievalNotifications(); notices.setEnabled(true);
    notices.consume(event("searching"));
    notices.consume({ ...event("", 2), type: "turn.accepted" });
    notices.consume(event("reading", 3));
    expect(notificationStore.getSnapshot()).toHaveLength(0);
    notices.consume(event("searching", 1, "b"));
    notices.consume(event("finished", 2, "b", { status: "ok" }));
    notices.setEnabled(false);
    expect(notificationStore.getSnapshot()).toHaveLength(0);
  });
  it("не создаёт карточку для ранее не виденного старого поколения", () => {
    const notices = new RetrievalNotifications(); notices.setEnabled(true);
    notices.consume({ ...event("", 1, "new", { generation: 3, turn_sequence: 8 }), type: "turn.accepted" });
    notices.consume(event("searching", 1, "old", { generation: 2, turn_sequence: 6 }));
    expect(notificationStore.getSnapshot()).toHaveLength(0);
    notices.consume(event("searching", 1, "new", { generation: 1, turn_sequence: 8 }));
    notices.consume(event("finished", 2, "new", { generation: 1, turn_sequence: 8, status: "cancelled", evidence_status: "partial" }));
    expect(notificationStore.getSnapshot()[0].message).toBe("Проверка отменена");
  });
});
