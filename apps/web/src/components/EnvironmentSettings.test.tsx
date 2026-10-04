// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useState } from "react";
import type { PublicSettings } from "../types";

const api = vi.hoisted(() => ({
  getEnvironmentStatus: vi.fn(), updateRuntimeSettings: vi.fn(), isDesktopManaged: vi.fn(),
  saveDesktopSearchApiKey: vi.fn(), removeDesktopSearchApiKey: vi.fn(), checkSearchProvider: vi.fn(), getSettings: vi.fn(),
}));
vi.mock("../api", () => api);
vi.mock("./CustomSelect", () => ({ CustomSelect: ({ children, value, onChange, disabled }: any) =>
  <select value={value} onChange={onChange} disabled={disabled}>{children}</select> }));
vi.mock("./MaterialButton", () => ({ MaterialButton: ({ materialKey, children, ...props }: any) =>
  <button {...props}>{children}</button> }));

import { EnvironmentSettings } from "./EnvironmentSettings";

function Harness({ initial = {} }: { initial?: Partial<PublicSettings> }) {
  const [settings, setSettings] = useState({ news_enabled: true, web_search_enabled: true,
    location_mode: "manual", search_api_keys_configured: {}, ...initial } as PublicSettings);
  return <EnvironmentSettings settings={settings} developerMode={false} onSettingsChanged={setSettings} />;
}

afterEach(cleanup);
beforeEach(() => {
  vi.resetAllMocks();
  api.isDesktopManaged.mockReturnValue(true);
  api.getEnvironmentStatus.mockResolvedValue({ status: "unavailable", location: {}, time: {} });
  api.saveDesktopSearchApiKey.mockResolvedValue({});
  api.removeDesktopSearchApiKey.mockResolvedValue({});
});

describe("настройки поискового API", () => {
  it("по умолчанию оставляет бесплатный поиск даже при сохранённых ключах", () => {
    render(<Harness initial={{ search_api_keys_configured: { brave: true } }} />);
    expect(screen.getByLabelText(/Источник веб-поиска/)).toHaveValue("free");
    expect(api.updateRuntimeSettings).not.toHaveBeenCalled();
    expect(api.checkSearchProvider).not.toHaveBeenCalled();
  });

  it("сохраняет ключ отдельно, очищает ввод и не переключает режим", async () => {
    api.getSettings.mockResolvedValue({ web_search_provider: "free", search_api_keys_configured: { brave: true } });
    render(<Harness />);
    fireEvent.change(screen.getByLabelText(/API-ключ поискового сервиса/), { target: { value: " test-key " } });
    fireEvent.click(screen.getByRole("button", { name: "Сохранить ключ" }));
    await waitFor(() => expect(api.saveDesktopSearchApiKey).toHaveBeenCalledWith("tavily", "test-key"));
    await waitFor(() => expect(screen.getByLabelText(/API-ключ поискового сервиса/)).toHaveValue(""));
    expect(screen.getByLabelText(/Источник веб-поиска/)).toHaveValue("free");
    expect(api.updateRuntimeSettings).not.toHaveBeenCalled();
    expect(api.checkSearchProvider).not.toHaveBeenCalled();
  });

  it("проверяет подключение только по кнопке и отдельно от выбранного режима", async () => {
    api.checkSearchProvider.mockResolvedValue({ provider: "tavily", status: "unauthorized" });
    render(<Harness initial={{ search_api_keys_configured: { tavily: true } }} />);
    fireEvent.click(screen.getByRole("button", { name: "Проверить подключение" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Ключ не принят"));
    expect(api.checkSearchProvider).toHaveBeenCalledExactlyOnceWith("tavily");
    expect(api.updateRuntimeSettings).not.toHaveBeenCalled();
  });

  it("показывает ошибку сохранения режима и оставляет прежний выбор", async () => {
    api.updateRuntimeSettings.mockRejectedValue(new Error("offline"));
    render(<Harness />);
    fireEvent.change(screen.getByLabelText(/Источник веб-поиска/), { target: { value: "tavily" } });
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Не удалось сохранить режим"));
    expect(screen.getByLabelText(/Источник веб-поиска/)).toHaveValue("free");
    expect(api.checkSearchProvider).not.toHaveBeenCalled();
  });
});
