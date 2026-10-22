// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ getCharacterState: vi.fn(), getCharacterStateEvents: vi.fn(), getCharacterReflections: vi.fn(), getReflectionSettings: vi.fn(), resetCharacterState: vi.fn(), updateReflectionSettings: vi.fn(), deleteCharacterReflection: vi.fn() }));
vi.mock("./api", () => api);
import { StatePage } from "./state";
import { eventEmotion, groupMoodCauses, relationshipLevel, stateEventLabel, timelineEmotion } from "./state-presentation";
import { timelineScrollFade } from "./state-timeline-scroll";

function mockCauses(causes: Array<{ label: string; status: string }>) {
  api.getCharacterState.mockResolvedValue({ mood: { primary_emotion: "playfulness", expression_strength: "moderate", secondary_emotions: [] }, relationship: { familiarity_label: "начальное", trust_label: "умеренный", current_dynamic: "спокойная" }, causes, incognito: false, updated_at: "2026-01-01T00:00:00Z" });
}

function stateEvent(id: string, event_kind: string, created_at = "2026-10-14T12:00:00Z") {
  return { id, event_kind, created_at, confidence: .9, intensity: .5, delta: {}, snippet: "Это пользовательский текст" };
}

beforeEach(() => {
  vi.stubGlobal("confirm", vi.fn(() => true));
  api.getCharacterState.mockResolvedValue({ mood: { primary_emotion: "hurt", expression_strength: "subtle", secondary_emotions: ["irritation"] }, relationship: { familiarity_label: "умеренное", trust_label: "осторожное", warmth_label: "сдержанная", tension_label: "есть", playfulness_label: "низкая", current_dynamic: "напряжённая", unresolved_cause: "insult" }, causes: [{ label: "insult", status: "active" }], incognito: false, updated_at: "2026-01-01T00:00:00Z" });
  api.getCharacterStateEvents.mockResolvedValue({ events: [] }); api.getCharacterReflections.mockResolvedValue({ reflections: [] }); api.getReflectionSettings.mockResolvedValue({ enabled: true, min_significance: .55 }); api.resetCharacterState.mockResolvedValue({}); api.updateReflectionSettings.mockResolvedValue({ enabled: false, min_significance: .55 });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("StatePage", () => {
  it("fades both scroll edges without hiding the beginning, end, or short content", () => {
    expect(timelineScrollFade(0, 400, 1200)).toEqual({ top: 0, bottom: 72 });
    expect(timelineScrollFade(200, 400, 1200)).toEqual({ top: 48, bottom: 72 });
    expect(timelineScrollFade(780, 400, 1200)).toEqual({ top: 48, bottom: 20 });
    expect(timelineScrollFade(900, 400, 1200)).toEqual({ top: 48, bottom: 0 });
    expect(timelineScrollFade(-20, 400, 1200)).toEqual({ top: 0, bottom: 72 });
    expect(timelineScrollFade(0, 400, 200)).toEqual({ top: 0, bottom: 0 });
    expect(timelineScrollFade(0, 0, 1200)).toEqual({ top: 0, bottom: 0 });
    const small = timelineScrollFade(100, 60, 400);
    expect(small.top + small.bottom).toBeLessThan(60);
  });

  it("uses recorded positive emotion impulses and the Iris palette", () => {
    expect(eventEmotion({ ...stateEvent("joy", "praise"), delta: { emotion_impulses: { neutral: 1, joy: .5, anxiety: .2, unknown: 10, hurt: -.8 } } }))
      .toEqual({ key: "joy", label: "Радость", tone: "success" });
    expect(eventEmotion(stateEvent("plain", "teasing"))).toBeNull();
    expect(timelineEmotion("hurt")?.tone).toBe("danger");
    expect(timelineEmotion("playfulness")?.tone).toBe("accent");
    expect(timelineEmotion("sadness")?.tone).toBe("quiet");
    expect(eventEmotion({ ...stateEvent("cooling", "neutral"), delta: { emotion_impulses: { anger: -.5, joy: 0 } } })).toBeNull();
    expect(timelineEmotion("__proto__")).toBeNull();
    expect(timelineEmotion("neutral")).toBeNull();
  });

  it("keeps a recorded emotion visible in the important filter and the header outside scrolling", async () => {
    api.getCharacterStateEvents.mockResolvedValue({ events: [
      { ...stateEvent("emotional", "neutral"), delta: { emotion_impulses: { anxiety: .6 } } },
      stateEvent("quiet", "neutral"),
    ] });
    render(<StatePage />);
    const emotion = await screen.findByText("Тревога");
    const item = emotion.closest("article")!;
    expect(item).toHaveAttribute("data-emotion", "anxiety");
    const card = item.querySelector(".timeline-content")!;
    expect(card).toHaveAttribute("data-emotion-tone", "warning");
    expect(card.querySelector(".dp-material")).toBeInTheDocument();
    expect(card).not.toHaveAttribute("role", "button");
    const viewport = screen.getByLabelText("Лента событий");
    expect(viewport).toContainElement(item);
    expect(viewport).toContainElement(item.querySelector(".timeline-marker"));
    expect(viewport).not.toContainElement(screen.getByRole("heading", { name: "События и заметки" }));
    expect(screen.getAllByRole("button", { name: /Спокойный диалог/ })).toHaveLength(1);
  });

  it("applies the same material to emotional notes and keeps plain events uncoloured", async () => {
    api.getCharacterStateEvents.mockResolvedValue({ events: [stateEvent("plain", "teasing")] });
    api.getCharacterReflections.mockResolvedValue({ reflections: [{ id: "note", created_at: "2026-10-14T13:00:00Z", primary_emotion: "hurt", trigger_label: "Непростой разговор", text: "Текст заметки Iris" }] });
    render(<StatePage />);
    const note = (await screen.findByText("Текст заметки Iris")).closest(".timeline-content")!;
    expect(note).toHaveAttribute("data-emotion-tone", "danger");
    expect(note.querySelector(".dp-material")).toBeInTheDocument();
    const plain = screen.getByText("«Это пользовательский текст»").closest(".timeline-content")!;
    expect(plain).not.toHaveAttribute("data-emotion-tone");
    expect(plain.querySelector(".dp-material")).toBeNull();
    fireEvent.click(within(note as HTMLElement).getByRole("button", { name: "Удалить" }));
    expect(screen.getByRole("alertdialog", { name: "Удалить заметку?" })).toBeInTheDocument();
    expect(api.deleteCharacterReflection).not.toHaveBeenCalled();
  });

  it("shows human-readable state, scoped reset, and reflection toggle", async () => {
    render(<StatePage />);
    expect(await screen.findByRole("heading", { name: "События и заметки" })).toBeInTheDocument();
    expect(screen.getByText("Что влияет на настроение")).toBeInTheDocument();
    expect(screen.getByText("Резкость / Защита границ")).toBeInTheDocument();
    expect(screen.queryByText("insult")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Сбросить настроение" }));
    fireEvent.click(screen.getByRole("button", { name: "Сбросить" }));
    await waitFor(() => expect(api.resetCharacterState).toHaveBeenCalledWith("mood"));
    fireEvent.click(screen.getByRole("checkbox", { name: "Личные заметки" }));
    await waitFor(() => expect(api.updateReflectionSettings).toHaveBeenCalled());
  });

  it("groups legacy codes and translated aliases without merging different statuses", () => {
    const groups = groupMoodCauses([
      { label: "teasing", status: "active" }, { label: "подкол / шутка", status: "активен" },
      { label: "shared success", status: "active" }, { label: "общий успех", status: "active" },
      { label: "teasing", status: "fading" }, { label: "Обсудили переезд", status: "active" },
    ]);
    expect(groups.map(({ label, status, count }) => ({ label, status, count }))).toEqual([
      { label: "Шутка / Подкол", status: "Влияет сейчас", count: 2 },
      { label: "Общий успех", status: "Влияет сейчас", count: 2 },
      { label: "Шутка / Подкол", status: "Затихает", count: 1 },
      { label: "Обсудили переезд", status: "Влияет сейчас", count: 1 },
    ]);
    expect(stateEventLabel("user_frustration")).toBe("Переживания пользователя");
    expect(stateEventLabel("internal_unknown_event")).toBe("Другой эпизод");
  });

  it("maps only known relationship labels to categorical levels", () => {
    expect(relationshipLevel("familiarity_label", "начальное")).toBe(1);
    expect(relationshipLevel("trust_label", "умеренный")).toBe(2);
    expect(relationshipLevel("warmth_label", "тёплая")).toBe(3);
    expect(relationshipLevel("tension_label", "нет")).toBe(0);
    expect(relationshipLevel("tension_label", "высокое")).toBe(3);
    expect(relationshipLevel("trust_label", "неизвестная оценка")).toBeNull();
  });

  it("shows relationship names and scales without visible value or mood badges", async () => {
    render(<StatePage />);
    const trust = await screen.findByRole("meter", { name: "Доверие" });
    expect(trust).toHaveAttribute("aria-valuenow", "1");
    expect(trust).toHaveAttribute("aria-valuetext", "осторожное");
    expect(screen.getAllByRole("meter")).toHaveLength(5);
    for (const text of ["умеренное", "осторожное", "сдержанная", "есть", "низкая", "напряжённая", "Сдержанное"]) {
      expect(screen.queryByText(text, { exact: true })).not.toBeInTheDocument();
    }
  });

  it("keeps both reset actions together and confirms the relationship scope", async () => {
    render(<StatePage />);
    const actions = await screen.findByRole("group", { name: "Сброс состояния" });
    expect(within(actions).getAllByRole("button")).toHaveLength(2);
    fireEvent.click(within(actions).getByRole("button", { name: "Сбросить отношения" }));
    expect(api.resetCharacterState).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Сбросить" }));
    await waitFor(() => expect(api.resetCharacterState).toHaveBeenCalledWith("relationship"));
  });

  it("keeps repeat causes compact and reveals other causes without writing state", async () => {
    mockCauses([
      ...Array.from({ length: 6 }, () => ({ label: "teasing", status: "active" })),
      ...["user frustration", "shared_success", "support", "praise"].map(label => ({ label, status: "active" })),
    ]);
    render(<StatePage />);
    const list = await screen.findByRole("list", { name: "Причины настроения" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(3);
    expect(within(list).getByText("×6")).toBeInTheDocument();
    expect(screen.getByRole("meter", { name: "Доверие" })).toHaveAttribute("aria-valuenow", "2");
    expect(screen.queryByText("умеренное")).not.toBeInTheDocument();
    const toggle = screen.getByRole("button", { name: /Ещё причины/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(within(list).getAllByRole("listitem")).toHaveLength(5);
    expect(list).toHaveAttribute("tabindex", "0");
    fireEvent.click(screen.getByRole("button", { name: "Свернуть" }));
    expect(within(list).getAllByRole("listitem")).toHaveLength(3);
    expect(api.resetCharacterState).not.toHaveBeenCalled();
    expect(api.updateReflectionSettings).not.toHaveBeenCalled();
  });

  it("separates quiet dialogue by local day and opens all events from a native button", async () => {
    api.getCharacterStateEvents.mockResolvedValue({ events: [
      stateEvent("today-1", "neutral"), stateEvent("today-2", "neutral", "2026-10-14T11:00:00Z"),
      stateEvent("yesterday", "neutral", "2026-10-13T12:00:00Z"), stateEvent("joke", "teasing", "2026-10-13T10:00:00Z"),
    ] });
    render(<StatePage />);
    const summaries = await screen.findAllByRole("button", { name: /Спокойный диалог/ });
    expect(summaries).toHaveLength(2);
    expect(summaries[0]).toHaveTextContent("· 2");
    expect(summaries[1]).toHaveTextContent("· 1");
    fireEvent.click(summaries[0]);
    expect(screen.queryByRole("button", { name: /Спокойный диалог/ })).not.toBeInTheDocument();
    expect(screen.getAllByText("Спокойная беседа")).toHaveLength(3);
    expect(screen.getAllByText("«Это пользовательский текст»")).toHaveLength(4);
    expect(document.querySelectorAll("time[datetime]")).toHaveLength(4);
  });

  it("keeps separate quiet groups stable when their timestamps match", async () => {
    api.getCharacterStateEvents.mockResolvedValue({ events: [
      stateEvent("quiet-1", "neutral"), stateEvent("joke", "teasing"),
      stateEvent("quiet-2", "neutral"), stateEvent("praise", "praise"), stateEvent("quiet-3", "neutral"),
    ] });
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    try {
      const { rerender } = render(<StatePage />);
      expect(await screen.findAllByRole("button", { name: /Спокойный диалог/ })).toHaveLength(3);
      rerender(<StatePage events={[{ type: "character.state.transition_applied" }]} />);
      expect(screen.getAllByRole("button", { name: /Спокойный диалог/ })).toHaveLength(3);
      expect(consoleError.mock.calls.some(([message]) => String(message).includes("same key"))).toBe(false);
    } finally { consoleError.mockRestore(); }
  });
});
