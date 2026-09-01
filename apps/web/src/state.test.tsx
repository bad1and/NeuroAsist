// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ getCharacterState: vi.fn(), getCharacterStateEvents: vi.fn(), getCharacterReflections: vi.fn(), getReflectionSettings: vi.fn(), resetCharacterState: vi.fn(), updateReflectionSettings: vi.fn(), deleteCharacterReflection: vi.fn() }));
vi.mock("./api", () => api);
vi.mock("@paper-design/shaders-react", () => ({ Metaballs: () => <div data-testid="metaballs" /> }));
import { StatePage } from "./state";

beforeEach(() => {
  vi.stubGlobal("confirm", vi.fn(() => true));
  api.getCharacterState.mockResolvedValue({ mood: { primary_emotion: "hurt", expression_strength: "subtle", secondary_emotions: ["irritation"] }, relationship: { familiarity_label: "умеренное", trust_label: "осторожное", warmth_label: "сдержанная", tension_label: "есть", playfulness_label: "низкая", current_dynamic: "напряжённая", unresolved_cause: "insult" }, causes: [{ label: "insult", status: "active" }], incognito: false, updated_at: "2026-01-01T00:00:00Z" });
  api.getCharacterStateEvents.mockResolvedValue({ events: [] }); api.getCharacterReflections.mockResolvedValue({ reflections: [] }); api.getReflectionSettings.mockResolvedValue({ enabled: true, min_significance: .55 }); api.resetCharacterState.mockResolvedValue({}); api.updateReflectionSettings.mockResolvedValue({ enabled: false, min_significance: .55 });
});
afterEach(() => vi.clearAllMocks());

describe("StatePage", () => {
  it("shows human-readable state, scoped reset, and reflection toggle", async () => {
    render(<StatePage />);
    expect(await screen.findByRole("heading", { name: "Живая история" })).toBeInTheDocument();
    expect(screen.getByText("Причины:")).toBeInTheDocument();
    expect(screen.getAllByText("insult").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "Сбросить настроение" }));
    await waitFor(() => expect(api.resetCharacterState).toHaveBeenCalledWith("mood"));
    fireEvent.click(screen.getByRole("checkbox", { name: "Личные заметки" }));
    await waitFor(() => expect(api.updateReflectionSettings).toHaveBeenCalled());
  });
});
