// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { BackendEvent } from "../types";
import { RetrievalProgress } from "./RetrievalProgress";

afterEach(cleanup);
const event = (phase: string, second: number, turn = "a", session = "s"): BackendEvent => ({
  id: `${turn}-${second}`, type: "retrieval.progress", level: "info", message: "Search progress",
  created_at: `2026-10-04T00:00:${String(second).padStart(2, "0")}Z`, metadata: { session_id: session, turn_id: turn, phase },
});

describe("ход проверки", () => {
  it("показывает этапы и очищается после завершения", () => {
    const { rerender } = render(<RetrievalProgress sessionId="s" events={[event("searching", 1)]} />);
    expect(screen.getByRole("status")).toHaveTextContent("Ищу");
    rerender(<RetrievalProgress sessionId="s" events={[event("reading", 2), event("searching", 1)]} />);
    expect(screen.getByRole("status")).toHaveTextContent("Читаю источники");
    rerender(<RetrievalProgress sessionId="s" events={[event("finished", 3), event("reading", 2), event("searching", 1)]} />);
    expect(screen.queryByRole("status")).toBeNull();
  });
  it("позднее завершение старого хода не скрывает новый поиск", () => {
    render(<RetrievalProgress sessionId="s" events={[event("finished", 4), event("refining", 3, "b"), event("searching", 2, "b"), event("searching", 1)]} />);
    expect(screen.getByRole("status")).toHaveTextContent("Уточняю запрос");
  });
  it("не показывает другую сессию", () => {
    render(<RetrievalProgress sessionId="s" events={[event("searching", 1, "a", "other")]} />);
    expect(screen.queryByRole("status")).toBeNull();
  });
});
