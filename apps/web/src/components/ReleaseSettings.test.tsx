// @vitest-environment jsdom
import "../test-setup";
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BackupControls } from "./BackupControls";
import { ModelManager } from "./ModelSettings";
import { StartupScreen } from "./StartupScreen";
import * as api from "../api";
import * as desktop from "../desktop";
import { notify } from "../notifications";
import { NotificationHost } from "./NotificationHost";

vi.mock("../api", () => ({ getBackups: vi.fn(), createBackup: vi.fn(), deleteBackup: vi.fn(), getModels: vi.fn(), installModel: vi.fn(), cancelModel: vi.fn(), removeModel: vi.fn() }));
vi.mock("./WindowChrome", () => ({ WindowChrome: () => null }));
vi.mock("../desktop", () => ({ isDesktopApp: () => true, exportDesktopBackup: vi.fn(), importDesktopBackup: vi.fn(), restoreDesktopBackup: vi.fn(), chooseModelDirectory: vi.fn(), removeManagedModel: vi.fn(), restartDesktopCore: vi.fn(), openModelInformation: vi.fn() }));

afterEach(() => { cleanup(); notify.dismissAll(); vi.clearAllMocks(); });
beforeEach(() => { vi.mocked(api.getBackups).mockResolvedValue([]); vi.mocked(api.getModels).mockResolvedValue({ models: [] }); });

describe("release settings", () => {
  it("offers recovery when the core cannot start", () => {
    const restore = vi.fn();
    render(<StartupScreen status="failed" onRestoreBackup={restore} />);
    fireEvent.click(screen.getByText("Восстановить из копии"));
    expect(restore).toHaveBeenCalledOnce();
  });

  it("does not report successful import after cancelling the file dialog", async () => {
    vi.mocked(desktop.importDesktopBackup).mockResolvedValue(null);
    render(<BackupControls />);
    fireEvent.click(screen.getByText("Загрузить копию из ZIP"));
    await screen.findByText("Резервных копий пока нет");
    expect(screen.queryByText("Импорт завершён.")).not.toBeInTheDocument();
  });
  it("shows all copies and requires confirmation before restoration", async () => {
    vi.mocked(api.getBackups).mockResolvedValue(Array.from({ length: 5 }, (_, index) => ({ name: `neuroasist-20261012T01000${index}Z.zip`, size_bytes: 1024, created_at: "2026-10-12" })));
    render(<BackupControls />);
    expect(await screen.findByText("neuroasist-20261012T010004Z.zip")).toBeInTheDocument();
    fireEvent.click(screen.getAllByText("Восстановить")[0]);
    expect(screen.getByText("Восстановить данные?")).toBeInTheDocument();
    expect(desktop.restoreDesktopBackup).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("Отмена"));
    expect(desktop.restoreDesktopBackup).not.toHaveBeenCalled();
  });

  it("offers model download without developer mode", async () => {
    vi.mocked(api.getModels).mockResolvedValue({ models: [{ id: "gigaam-v3-rnnt", name: "GigaAM", version: "revision", installed: false, size_bytes: 1000, sha256: "hash", restart_required: true, status: "not_installed", downloaded_bytes: 0, total_bytes: 1000 }] });
    render(<ModelManager developerMode={false} />);
    fireEvent.click(await screen.findByText("Скачать"));
    expect(api.installModel).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("Начать загрузку"));
    expect(api.installModel).toHaveBeenCalledWith("gigaam-v3-rnnt");
  });

  it("allows cancelling an active download", async () => {
    vi.mocked(api.getModels).mockResolvedValue({ models: [{ id: "teratts-v2", name: "TeraTTS", version: "revision", installed: false, size_bytes: 1000, sha256: "hash", restart_required: true, status: "downloading", downloaded_bytes: 500, total_bytes: 1000 }] });
    render(<ModelManager />);
    fireEvent.click(await screen.findByText("Отменить загрузку"));
    expect(api.cancelModel).toHaveBeenCalledWith("teratts-v2");
  });

  it("lets the user cancel folder selection and the download without installing", async () => {
    vi.mocked(api.getModels).mockResolvedValue({ directory: "D:/models", models: [{ id: "silero-vad", name: "Silero", version: "6", installed: false, size_bytes: 1000, sha256: "hash", restart_required: true, status: "not_installed", downloaded_bytes: 0, total_bytes: 1000 }] });
    vi.mocked(desktop.chooseModelDirectory).mockResolvedValue(null);
    render(<ModelManager />);
    fireEvent.click(await screen.findByText("Скачать"));
    fireEvent.click(screen.getAllByText("Выбрать папку")[1]);
    await waitFor(() => expect(desktop.chooseModelDirectory).toHaveBeenCalledOnce());
    await waitFor(() => expect(screen.getByText("Начать загрузку")).not.toBeDisabled());
    fireEvent.click(screen.getByText("Отмена"));
    expect(api.installModel).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.getAllByText("D:/models")).toHaveLength(1));
  });

  it("reports backup success through the notification host", async () => {
    vi.mocked(api.createBackup).mockResolvedValue({ name: "copy.zip", size_bytes: 1, created_at: "today" });
    const { container } = render(<><BackupControls /><NotificationHost /></>);
    fireEvent.click(screen.getByText("Создать копию"));
    const message = await screen.findByText("Резервная копия создана.");
    expect(message.closest(".notification-card")).not.toBeNull();
    expect(container.querySelector(".notice")).toBeNull();
  });

  it("offers optional upstream information without adding a download gate", async () => {
    const source = "https://huggingface.co/TeraSpace/TeraTTSv2/tree/revision";
    const terms = "https://huggingface.co/terms-of-service";
    vi.mocked(api.getModels).mockResolvedValue({ models: [{ id: "teratts-v2", name: "TeraTTS", version: "revision", installed: false, size_bytes: 1000, sha256: "hash", restart_required: true, status: "not_installed", downloaded_bytes: 0, total_bytes: 1000, delivery: "upstream_download", source_url: source, terms_url: terms }] });
    render(<ModelManager />);
    expect(await screen.findByRole("button", { name: "Источник модели" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(api.installModel).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("Источник модели"));
    await waitFor(() => expect(desktop.openModelInformation).toHaveBeenCalledWith("teratts-v2", "source", source));
    await waitFor(() => expect(screen.getByText("Скачать")).toBeEnabled());
    fireEvent.click(screen.getByText("Условия использования"));
    await waitFor(() => expect(desktop.openModelInformation).toHaveBeenCalledWith("teratts-v2", "terms", terms));
    await waitFor(() => expect(screen.getByText("Скачать")).toBeEnabled());
    fireEvent.click(screen.getByText("Скачать"));
    fireEvent.click(screen.getByText("Начать загрузку"));
    expect(api.installModel).toHaveBeenCalledWith("teratts-v2");
  });

  it("waits for core reconnection after choosing storage without a false error", async () => {
    vi.mocked(api.getModels).mockResolvedValue({ directory: "C:/models", models: [] });
    vi.mocked(desktop.chooseModelDirectory).mockImplementation(async () => {
      vi.mocked(api.getModels).mockRejectedValueOnce(new Error("core restarting"))
        .mockResolvedValue({ directory: "D:/Iris-models", models: [] });
      return { directory: "D:/Iris-models" };
    });
    render(<><ModelManager /><NotificationHost /></>);
    await screen.findByText("C:/models");
    fireEvent.click(screen.getByText("Выбрать папку"));
    await screen.findByText("D:/Iris-models");
    await waitFor(() => expect(screen.getByText("Выбрать папку")).not.toBeDisabled());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
