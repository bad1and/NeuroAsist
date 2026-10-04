// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useState } from "react";
import type { PublicSettings } from "../types";
const api = vi.hoisted(() => ({ getSettings: vi.fn(), checkSearchProvider: vi.fn(),
  saveDesktopApiKey: vi.fn(), saveDesktopCodingApiKey: vi.fn(), saveDesktopSearchApiKey: vi.fn(),
  removeDesktopApiKey: vi.fn(), removeDesktopCodingApiKey: vi.fn(), removeDesktopSearchApiKey: vi.fn() }));
const desktop = vi.hoisted(() => ({ isDesktopApp: vi.fn(), openApiKeyPortal: vi.fn() }));
vi.mock("../api", () => api);
vi.mock("../desktop", () => desktop);
vi.mock("./MaterialButton", () => ({ MaterialButton: ({ materialKey, children, ...props }: any) =>
  <button {...props}>{children}</button> }));
import { ApiKeysSettings } from "./ApiKeysSettings";
const initial = { api_key_configured: true, coding_api_key_configured: true, web_search_provider: "free",
  search_api_keys_configured: {} } as PublicSettings;
const changed = vi.fn();
function Harness({ initialSettings = initial, active = true }: { initialSettings?: PublicSettings; active?: boolean }) {
  const [settings, setSettings] = useState(initialSettings);
  return <ApiKeysSettings settings={settings} active={active} onSettingsChanged={next => { changed(next); setSettings(next); }} />;
}
function card(title: string) { return within(screen.getByRole("region", { name: title })); }
afterEach(() => { cleanup(); vi.useRealTimers(); });
beforeEach(() => {
  vi.resetAllMocks();
  desktop.isDesktopApp.mockReturnValue(true);
  api.getSettings.mockResolvedValue(initial);
  api.saveDesktopApiKey.mockResolvedValue({});
  api.saveDesktopCodingApiKey.mockResolvedValue({});
  api.saveDesktopSearchApiKey.mockResolvedValue({});
  api.removeDesktopApiKey.mockResolvedValue({});
  api.removeDesktopCodingApiKey.mockResolvedValue({});
  api.removeDesktopSearchApiKey.mockResolvedValue({});
});
describe("единый раздел ключей", () => {
  it.each([["DeepSeek API", "deepseek"], ["Coding Agent API", "deepseek"], ["Tavily API", "tavily"]])("открывает кабинет для %s", async (title, provider) => {
    render(<Harness />);
    fireEvent.click(card(title).getByRole("button", { name: "Получить API-ключ" }));
    expect(desktop.openApiKeyPortal).toHaveBeenCalledWith(provider);
    expect(screen.queryByText("Вернуться к настройкам поиска")).toBeNull();
    expect(screen.queryByText("Значение хранится локально и никогда не отображается обратно.")).toBeNull();
    expect(api.saveDesktopApiKey).not.toHaveBeenCalled();
  });
  it("показывает ошибку открытия в соответствующей карточке", async () => {
    desktop.openApiKeyPortal.mockRejectedValue(new Error("unavailable"));
    render(<Harness />);
    fireEvent.click(card("Tavily API").getByRole("button", { name: "Получить API-ключ" }));
    expect(await card("Tavily API").findByRole("alert")).toHaveTextContent("Не удалось открыть кабинет");
  });
  it.each(["deepseek", "coding", "tavily"] as const)("сохраняет %s и повторяет только чтение при запуске ядра", async kind => {
    const labels = { deepseek: "API-ключ DeepSeek", coding: "API-ключ Coding Agent", tavily: "API-ключ Tavily" };
    const titles = { deepseek: "DeepSeek API", coding: "Coding Agent API", tavily: "Tavily API" };
    const commands = { deepseek: api.saveDesktopApiKey, coding: api.saveDesktopCodingApiKey, tavily: api.saveDesktopSearchApiKey };
    api.getSettings.mockRejectedValueOnce(new Error("restarting"))
      .mockResolvedValue({ ...initial, search_api_keys_configured: { tavily: true } });
    render(<Harness />);
    fireEvent.change(screen.getByLabelText(labels[kind]), { target: { value: " fixture-key " } });
    fireEvent.click(card(titles[kind]).getByRole("button", { name: kind === "tavily" ? "Сохранить ключ" : "Заменить ключ" }));
    await waitFor(() => expect(commands[kind]).toHaveBeenCalledOnce());
    if (kind === "tavily") expect(commands[kind]).toHaveBeenCalledWith("tavily", "fixture-key");
    else expect(commands[kind]).toHaveBeenCalledWith("fixture-key");
    await waitFor(() => expect(api.getSettings).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(card(titles[kind]).getByRole("status")).toHaveTextContent("Ключ сохранён"));
    expect(screen.getByLabelText(labels[kind])).toHaveValue("");
    expect(commands[kind]).toHaveBeenCalledOnce();
    expect(changed).toHaveBeenLastCalledWith(expect.objectContaining({ web_search_provider: "free" }));
    expect(api.checkSearchProvider).not.toHaveBeenCalled();
  });
  it("отдельно сообщает задержку ядра после успешной команды", async () => {
    vi.useFakeTimers();
    api.getSettings.mockRejectedValue(new Error("restarting"));
    render(<Harness />);
    fireEvent.change(screen.getByLabelText("API-ключ Tavily"), { target: { value: "fixture" } });
    fireEvent.click(card("Tavily API").getByRole("button", { name: "Сохранить ключ" }));
    await act(async () => { await vi.runAllTimersAsync(); });
    expect(api.getSettings).toHaveBeenCalledTimes(20);
    expect(api.saveDesktopSearchApiKey).toHaveBeenCalledOnce();
    expect(card("Tavily API").getByRole("status")).toHaveTextContent("Ключ сохранён");
    expect(card("Tavily API").getByRole("status")).toHaveTextContent("Ядро ещё запускается");
    expect(card("Tavily API").queryByRole("alert")).toBeNull();
  });
  it("сохраняет ввод после отказа команды и показывает ошибку только у нужного ключа", async () => {
    api.saveDesktopSearchApiKey.mockRejectedValue(new Error("keyring"));
    render(<Harness />);
    fireEvent.change(screen.getByLabelText("API-ключ Tavily"), { target: { value: "fixture" } });
    fireEvent.click(card("Tavily API").getByRole("button", { name: "Сохранить ключ" }));
    expect(await card("Tavily API").findByRole("alert")).toHaveTextContent("Не удалось сохранить ключ");
    expect(screen.getByLabelText("API-ключ Tavily")).toHaveValue("fixture");
    expect(api.getSettings).not.toHaveBeenCalled();
    expect(card("DeepSeek API").queryByRole("alert")).toBeNull();
  });
  it("проверяет Tavily только по кнопке и показывает квоту", async () => {
    api.checkSearchProvider.mockResolvedValue({ status: "quota_exhausted", quota: { used: 900, limit: 900 } });
    render(<Harness initialSettings={{ ...initial, search_api_keys_configured: { tavily: true } }} />);
    expect(api.checkSearchProvider).not.toHaveBeenCalled();
    fireEvent.click(card("Tavily API").getByRole("button", { name: "Проверить подключение" }));
    expect(await card("Tavily API").findByRole("alert")).toHaveTextContent("Расход: 900 / 900");
    expect(api.checkSearchProvider).toHaveBeenCalledExactlyOnceWith("tavily");
    expect(api.saveDesktopSearchApiKey).not.toHaveBeenCalled();
  });
  it("показывает только сохранённые старые ключи и позволяет удалить их", async () => {
    api.getSettings.mockResolvedValue(initial);
    render(<Harness initialSettings={{ ...initial, search_api_keys_configured: { brave: true } }} />);
    expect(screen.queryByRole("region", { name: "Serper API" })).toBeNull();
    const brave = card("Brave API");
    expect(brave.queryByRole("button", { name: /Сохранить|Заменить|Проверить/ })).toBeNull();
    expect(brave.queryByLabelText("API-ключ Brave")).toBeNull();
    fireEvent.click(brave.getByRole("button", { name: "Удалить" }));
    await waitFor(() => expect(screen.queryByRole("region", { name: "Brave API" })).toBeNull());
    expect(api.removeDesktopSearchApiKey).toHaveBeenCalledExactlyOnceWith("brave");
  });
  it("блокирует управление хранилищем в браузере", () => {
    desktop.isDesktopApp.mockReturnValue(false);
    render(<Harness />);
    expect(screen.getByLabelText("API-ключ DeepSeek")).toBeDisabled();
    expect(card("Tavily API").getByRole("button", { name: "Сохранить ключ" })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("в установленном приложении Iris");
  });
  it("очищает несохранённые секреты при уходе из раздела", () => {
    const { rerender } = render(<Harness />);
    fireEvent.change(screen.getByLabelText("API-ключ DeepSeek"), { target: { value: "fixture" } });
    rerender(<Harness active={false} />);
    expect(screen.getByLabelText("API-ключ DeepSeek")).toHaveValue("");
  });
  it.each(["deepseek", "coding", "tavily"] as const)("удаляет %s через его отдельную команду", async kind => {
    const titles = { deepseek: "DeepSeek API", coding: "Coding Agent API", tavily: "Tavily API" };
    const commands = { deepseek: api.removeDesktopApiKey, coding: api.removeDesktopCodingApiKey, tavily: api.removeDesktopSearchApiKey };
    render(<Harness initialSettings={{ ...initial, search_api_keys_configured: { tavily: true } }} />);
    fireEvent.click(card(titles[kind]).getByRole("button", { name: "Удалить" }));
    await waitFor(() => expect(commands[kind]).toHaveBeenCalledOnce());
    await waitFor(() => expect(card(titles[kind]).getByRole("status")).toHaveTextContent("Ключ удалён"));
  });
});
