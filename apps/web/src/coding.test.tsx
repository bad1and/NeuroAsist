// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getCodingStatus: vi.fn(),
  getCodingTasks: vi.fn(),
  getCodingTask: vi.fn(),
  createCodingTask: vi.fn(),
  addCodingInstruction: vi.fn(),
  cancelCodingTask: vi.fn(),
  retryCodingTask: vi.fn(),
  applyCodingTask: vi.fn(),
  clearCodingTasks: vi.fn(),
  updateRuntimeSettings: vi.fn(),
}));

vi.mock("./api", () => api);

import { CodingAgentPage } from "./coding";
import type { CodingStatus, CodingTask, PublicSettings } from "./types";

const mockStatus: CodingStatus = {
  enabled: true,
  configured_enabled: true,
  available: true,
  availability_reason: null,
  docker_cli_available: true,
  docker_daemon_available: true,
  docker_image_available: true,
  docker_image_name: "neuroasist-sandbox:latest",
  model: "deepseek-coder",
  available_models: ["deepseek-coder", "claude-3-5-sonnet"],
  project_root: "d:/NeroPizda/NeuroAsist",
  allowed_project_roots: ["d:/NeroPizda/NeuroAsist", "d:/other/repo"],
  workspace_name: "test-workspace",
  workspace_root: "d:/NeroPizda/NeuroAsist/.agents/coding",
  auto_delegate: true,
  queued_count: 0,
};

const mockTasks: CodingTask[] = [
  {
    id: "task-1",
    objective: "Написать юнит-тесты для модуля валидации",
    model: "deepseek-coder",
    project_root: "d:/NeroPizda/NeuroAsist",
    workspace_name: "test-workspace",
    status: "running",
    cancellation_requested: false,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    context_files: ["apps/web/src/App.tsx"],
    base_manifest: {},
    result: { summary: "Тесты генерируются..." },
    patch_text: "--- a/test.ts\n+++ b/test.ts\n@@ -0,0 +1,5 @@\n+test('sample', () => {});",
    events: [
      {
        id: 1,
        task_id: "task-1",
        type: "log",
        level: "info",
        message: "Запуск контейнера песочницы",
        payload: {},
        created_at: new Date().toISOString(),
      },
    ],
    instructions: [],
  },
  {
    id: "task-2",
    objective: "Исправить синтаксическую ошибку в парсере",
    model: "deepseek-coder",
    project_root: "d:/NeroPizda/NeuroAsist",
    workspace_name: "test-workspace",
    status: "review_ready",
    cancellation_requested: false,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    context_files: [],
    base_manifest: {},
    result: { summary: "Ошибка исправлена", tests: "PASSED 3/3" },
    patch_text: "--- a/parser.ts\n+++ b/parser.ts\n@@ -10 +10 @@\n-const a\n+const a = 1;",
    events: [],
    instructions: [],
  },
];

const mockSettings = {
  coding_agent_enabled: true,
  coding_auto_delegate: true,
  coding_api_key_configured: true,
  coding_model: "deepseek-coder",
  coding_project_root: "d:/NeroPizda/NeuroAsist",
  coding_workspace_name: "test-workspace",
  coding_available_models: ["deepseek-coder", "claude-3-5-sonnet"],
  coding_allowed_project_roots: ["d:/NeroPizda/NeuroAsist", "d:/other/repo"],
} as unknown as PublicSettings;

describe("CodingAgentPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getCodingStatus.mockResolvedValue(mockStatus);
    api.getCodingTasks.mockResolvedValue(mockTasks);
    api.getCodingTask.mockImplementation(async (id: string) => mockTasks.find((t) => t.id === id) ?? mockTasks[0]);
  });

  afterEach(() => {
    cleanup();
  });

  it("рендерит панель с боковым меню и подразделами", async () => {
    render(
      <CodingAgentPage
        settings={mockSettings}
        events={[]}
        sessionId="sess-1"
        onSettingsChanged={vi.fn()}
      />
    );

    await waitFor(() => {
      const nav = screen.getByRole("navigation", { name: /Разделы Coding Agent/i });
      expect(within(nav).getByText("Задачи")).toBeInTheDocument();
      expect(within(nav).getByText("Новая задача")).toBeInTheDocument();
      expect(within(nav).getByText("Песочница Docker")).toBeInTheDocument();
      expect(within(nav).getByText("Параметры")).toBeInTheDocument();
    });

    // Проверяем список задач в галерее
    await waitFor(() => {
      expect(screen.getByText("Написать юнит-тесты для модуля валидации")).toBeInTheDocument();
    });

    // Кликаем по задаче для открытия подробного просмотра
    fireEvent.click(screen.getByText("Написать юнит-тесты для модуля валидации"));

    await waitFor(() => {
      expect(screen.getByText("Запуск контейнера песочницы")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /Назад к списку задач/i })).toBeInTheDocument();
    });

    // Возвращаемся назад к списку
    fireEvent.click(screen.getByRole("button", { name: /Назад к списку задач/i }));
    await waitFor(() => {
      expect(screen.getByText("Исправить синтаксическую ошибку в парсере")).toBeInTheDocument();
    });
  });

  it("переключает подразделы меню", async () => {
    render(
      <CodingAgentPage
        settings={mockSettings}
        events={[]}
        sessionId="sess-1"
        onSettingsChanged={vi.fn()}
      />
    );

    const nav = await screen.findByRole("navigation", { name: /Разделы Coding Agent/i });
    expect(within(nav).getByText("Новая задача")).toBeInTheDocument();

    // Переходим в раздел «Новая задача» через боковое меню
    fireEvent.click(within(nav).getByRole("button", { name: /Новая задача/i }));
    await waitFor(() => {
      expect(screen.getByText("Постановка задачи")).toBeInTheDocument();
      expect(screen.getByPlaceholderText(/напиши вспомогательный модуль/i)).toBeInTheDocument();
    });

    // Переходим в раздел «Песочница Docker»
    fireEvent.click(within(nav).getByRole("button", { name: /Песочница Docker/i }));
    await waitFor(() => {
      expect(screen.getByText("Песочница и окружение Docker")).toBeInTheDocument();
      expect(screen.getByText("Docker Daemon")).toBeInTheDocument();
      expect(screen.getByText("Параметры окружения")).toBeInTheDocument();
    });

    // Переходим в раздел «Параметры»
    fireEvent.click(within(nav).getByRole("button", { name: /Параметры/i }));
    await waitFor(() => {
      expect(screen.getByText("Параметры кодинг-агента")).toBeInTheDocument();
      expect(screen.getByText("Включить Coding Agent")).toBeInTheDocument();
      expect(screen.getByText("Автоделегирование из диалога")).toBeInTheDocument();
    });
  });

  it("фильтрует список задач по статусам и поисковому запросу", async () => {
    const { container } = render(
      <CodingAgentPage
        settings={mockSettings}
        events={[]}
        sessionId="sess-1"
        onSettingsChanged={vi.fn()}
      />
    );

    await waitFor(() => {
      const taskList = container.querySelector(".coding-tasks-grid");
      expect(taskList).toBeInTheDocument();
      expect(within(taskList as HTMLElement).getByText("Написать юнит-тесты для модуля валидации")).toBeInTheDocument();
    });

    const taskList = container.querySelector(".coding-tasks-grid")!;

    // Фильтр "Ревью"
    fireEvent.click(screen.getByRole("button", { name: "Ревью" }));
    await waitFor(() => {
      expect(within(taskList as HTMLElement).getByText("Исправить синтаксическую ошибку в парсере")).toBeInTheDocument();
      expect(within(taskList as HTMLElement).queryByText("Написать юнит-тесты для модуля валидации")).not.toBeInTheDocument();
    });

    // Поиск
    const searchInput = screen.getByPlaceholderText("Поиск по задачам");
    fireEvent.change(searchInput, { target: { value: "синтаксическую" } });
    expect(within(taskList as HTMLElement).getByText("Исправить синтаксическую ошибку в парсере")).toBeInTheDocument();
  });
});
