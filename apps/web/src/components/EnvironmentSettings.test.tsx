// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useState } from "react";
import type { PublicSettings } from "../types";
import { useRuntimeSettingsAutosave, type RuntimeSettingsPatch } from "../settingsAutosave";

const api = vi.hoisted(() => ({ getEnvironmentStatus: vi.fn(), updateRuntimeSettings: vi.fn() }));
vi.mock("../api", () => api);
vi.mock("./CustomSelect", () => ({ CustomSelect: ({ children, value, onChange, disabled }: any) =>
  <select value={value} onChange={onChange} disabled={disabled}>{children}</select> }));
vi.mock("./MaterialButton", () => ({ MaterialButton: ({ materialKey, children, ...props }: any) =>
  <button {...props}>{children}</button> }));
import { EnvironmentSettings } from "./EnvironmentSettings";
const openKeys = vi.fn();
let server: PublicSettings;
function Harness({ initial = {} }: { initial?: Partial<PublicSettings> }) {
  const [settings, setSettings] = useState(() => {
    server = { news_enabled: true, weather_enabled: true, web_search_enabled: true,
      location_mode: "manual", location_city: "Москва", search_api_keys_configured: {}, ...initial } as PublicSettings;
    return server;
  });
  const autosave = useRuntimeSettingsAutosave(next => { server = next; }, server, (next, fields) => {
    setSettings(current => ({ ...current, ...Object.fromEntries(fields.map(field => [field, next[field]])) }));
  });
  const save = (patch: RuntimeSettingsPatch, rollback?: () => void, committed?: (next: PublicSettings) => void) => {
    setSettings(current => ({ ...current, ...patch }));
    return autosave.save(patch, rollback, committed);
  };
  return <>
    {autosave.status === "error" && <button onClick={autosave.retry}>Повторить</button>}
    <EnvironmentSettings settings={settings} developerMode={false} onSaveSetting={save} onOpenApiKeys={openKeys} />
  </>;
}
afterEach(cleanup);
beforeEach(() => {
  vi.resetAllMocks();
  api.getEnvironmentStatus.mockResolvedValue({ status: "unavailable" });
  api.updateRuntimeSettings.mockImplementation(async patch => ({ ...server, ...patch }));
});

describe("окружение и гео", () => {
  it("оставляет управление ключами в отдельном разделе и не меняет режим при открытии", async () => {
    render(<Harness initial={{ search_api_keys_configured: { tavily: true } }} />);
    expect(screen.getByLabelText(/Источник веб-поиска/)).toHaveValue("free");
    expect(screen.queryByLabelText(/API-ключ поискового сервиса/)).toBeNull();
    expect(document.querySelector('input[type="password"]')).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Настроить API-ключ" }));
    expect(openKeys).toHaveBeenCalledOnce();
    expect(api.updateRuntimeSettings).not.toHaveBeenCalled();
    await screen.findByText(/Окружение пока недоступно/);
    expect(screen.queryByText("Загрузка…")).toBeNull();
  });
  it("блокирует выбор источника при выключенном поиске, сохраняя выбор", () => {
    render(<Harness initial={{ web_search_enabled: false, web_search_provider: "tavily" }} />);
    expect(screen.getByLabelText(/Источник веб-поиска/)).toBeDisabled();
    expect(screen.getByLabelText(/Источник веб-поиска/)).toHaveValue("tavily");
  });
  it("откатывает переключатель после ошибки и применяет успешный повтор", async () => {
    api.updateRuntimeSettings.mockRejectedValueOnce(new Error("offline"));
    render(<Harness />);
    const toggle = screen.getByRole("switch", { name: /Погода за окном/ });
    fireEvent.click(toggle);
    await screen.findByRole("button", { name: "Повторить" });
    expect(toggle).toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
    await waitFor(() => expect(toggle).not.toBeChecked());
  });
  it("сохраняет город только по подтверждению и удерживает черновик после ошибки", async () => {
    api.updateRuntimeSettings.mockRejectedValueOnce(new Error("offline"));
    render(<Harness />);
    const city = screen.getByLabelText("Город");
    fireEvent.change(city, { target: { value: " Сочи " } });
    expect(api.updateRuntimeSettings).not.toHaveBeenCalled();
    fireEvent.keyDown(city, { key: "Enter" });
    await screen.findByRole("button", { name: "Повторить" });
    expect(city).toHaveValue(" Сочи ");
    expect(screen.queryByRole("button", { name: "Сохранено ✓" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Повторить" }));
    await screen.findByRole("button", { name: "Сохранено ✓" });
    expect(city).toHaveValue("Сочи");
    expect(api.updateRuntimeSettings).toHaveBeenLastCalledWith({ location_city: "Сочи" });
  });
  it("не отправляет пустой город", () => {
    render(<Harness />);
    const city = screen.getByLabelText("Город");
    fireEvent.change(city, { target: { value: "  " } });
    fireEvent.keyDown(city, { key: "Enter" });
    expect(api.updateRuntimeSettings).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Сохранить" })).toBeDisabled();
  });
  it("не затирает новый черновик города ответом на старое сохранение", async () => {
    let resolve!: (value: PublicSettings) => void;
    api.updateRuntimeSettings.mockImplementationOnce(() => new Promise(done => { resolve = done; }));
    render(<Harness />);
    const city = screen.getByLabelText("Город");
    fireEvent.change(city, { target: { value: "Сочи" } });
    fireEvent.keyDown(city, { key: "Enter" });
    fireEvent.change(city, { target: { value: "Казань" } });
    resolve({ ...server, location_city: "Сочи" });
    await waitFor(() => expect(screen.getByRole("button", { name: "Сохранить" })).not.toBeDisabled());
    expect(city).toHaveValue("Казань");
    expect(screen.queryByRole("button", { name: "Сохранено ✓" })).toBeNull();
  });
  it("показывает приблизительный источник города и время устройства", async () => {
    api.getEnvironmentStatus.mockResolvedValue({ status: "active", location: { city: "Москва", source: "timezone_fallback" },
      time: { formatted_time: "12:30", weekday: "воскресенье" } });
    render(<Harness />);
    expect(await screen.findByText("Москва (примерно, по часовому поясу)")).toBeInTheDocument();
    expect(screen.getByText("Время на устройстве")).toBeInTheDocument();
  });
});
