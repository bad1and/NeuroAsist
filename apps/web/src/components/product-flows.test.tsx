// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ButtonHTMLAttributes, ReactNode } from "react";

const api = vi.hoisted(() => ({ requestJson: vi.fn(), getVoicePreview: vi.fn() }));
const reminders = vi.hoisted(() => ({ getReminders: vi.fn(), updateReminder: vi.fn() }));
vi.mock("../api", () => api);
vi.mock("../product-api", () => reminders);
vi.mock("./ReminderDelivery", () => ({ allowReminderNotifications: vi.fn().mockResolvedValue(false) }));
vi.mock("./AppDialog", () => ({ AppDialog: ({ open, children }: { open: boolean; children: ReactNode }) => open ? <div role="dialog">{children}</div> : null }));
vi.mock("./MaterialButton", () => ({ MaterialButton: ({ materialKey: _key, appearance: _appearance, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { materialKey?: string; appearance?: string }) => <button {...props} /> }));
vi.mock("animejs", () => ({ createTimer: vi.fn(() => ({ cancel: vi.fn() })) }));
vi.mock("../audio-devices", () => ({ setAudioElementOutput: vi.fn().mockResolvedValue(undefined) }));

import { GlobalSearch } from "./GlobalSearch";
import { AudioCheck } from "./AudioCheck";
import { DocumentAttachment } from "./DocumentAttachment";
import { RemindersPanel } from "./RemindersPanel";
import { PatchReview, splitPatch } from "./PatchReview";
import { searchSettings } from "../search-navigation";
import { DocumentSources } from "./MemoryContextDetails";
import { useInterfaceLocale } from "../i18n";

const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
};
beforeEach(() => { vi.clearAllMocks(); localStorage.clear(); api.requestJson.mockResolvedValue({ items: [], document: null }); reminders.getReminders.mockResolvedValue({ items: [] }); });
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); });

describe("global search navigation", () => {
  it("translates settings results while preserving user plan titles and excerpts", async () => {
    function LocalizedSearch() {
      useInterfaceLocale("en");
      return <GlobalSearch open developerMode={false} onClose={vi.fn()} onSelect={vi.fn()} />;
    }
    const view = render(<LocalizedSearch />);
    await waitFor(() => expect(screen.getByText("Environment & location")).toBeInTheDocument());
    api.requestJson.mockImplementation((path: string) => Promise.resolve({ items: path.startsWith("/memory/commitments")
      ? [{ id: "user-plan", title: "Настройки", details: "Сохранено" }] : [] }));
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "user-plan" } });
    await screen.findByText("Настройки", { selector: "strong" });
    await waitFor(() => expect(screen.getByText("Сохранено")).toBeInTheDocument());
    expect(view.container.querySelector("strong[data-i18n-skip]")).toHaveTextContent("Настройки");
  });
  it("ignores a delayed old query and opens the exact result with Enter", async () => {
    vi.useFakeTimers();
    const old = deferred<{ items: unknown[] }>();
    api.requestJson.mockImplementation((path: string) => {
      if (path.includes("q=old")) return old.promise;
      return Promise.resolve({ items: path.startsWith("/timeline") ? [{ id: "exact-message", role: "user", content: "new result", created_at: "2026-10-19T10:00:00Z" }] : [] });
    });
    const select = vi.fn();
    render(<GlobalSearch open developerMode={false} onClose={vi.fn()} onSelect={select} />);
    const input = screen.getByRole("combobox");
    fireEvent.change(input, { target: { value: "old" } });
    await act(() => vi.advanceTimersByTimeAsync(190));
    fireEvent.change(input, { target: { value: "new" } });
    await act(() => vi.advanceTimersByTimeAsync(190));
    expect(screen.getByText("new result")).toBeInTheDocument();
    await act(async () => old.resolve({ items: [] }));
    expect(screen.getByText("new result")).toBeInTheDocument();
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(select).toHaveBeenCalledWith(expect.objectContaining({ kind: "history", focus: expect.objectContaining({ id: "exact-message", query: "new" }) }));
  });
  it("keeps developer sections out of ordinary settings results", () => {
    expect(searchSettings("", false).some(item => item.section === "maintenance")).toBe(false);
    expect(searchSettings("", true).some(item => item.section === "maintenance")).toBe(true);
  });
  it("keeps available search groups when one source fails", async () => {
    vi.useFakeTimers();
    api.requestJson.mockImplementation((path: string) => path.startsWith("/timeline") ? Promise.reject(new Error("offline")) : Promise.resolve({ items: path.startsWith("/memory?") ? [{ id: "fact", value_text: "Сохранённая настройка" }] : [] }));
    render(<GlobalSearch open developerMode={false} onClose={vi.fn()} onSelect={vi.fn()} />);
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "факт" } });
    await act(() => vi.advanceTimersByTimeAsync(190));
    expect(screen.getByText("Сохранённая настройка")).toBeInTheDocument();
    expect(screen.getByText(/Сейчас недоступны: история/)).toBeInTheDocument();
  });
});

describe("explicit audio checks", () => {
  it("does not capture on mount and stops a stream arriving after cancellation", async () => {
    const input = deferred<MediaStream>();
    const capture = vi.fn(() => input.promise), stop = vi.fn();
    Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia: capture } });
    render(<AudioCheck inputDeviceId="chosen-mic" />);
    expect(capture).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Проверить микрофон" }));
    expect(capture).toHaveBeenCalledWith({ audio: { deviceId: { exact: "chosen-mic" } }, video: false });
    fireEvent.click(screen.getByRole("button", { name: "Остановить проверку" }));
    await act(async () => input.resolve({ getTracks: () => [{ stop }] } as unknown as MediaStream));
    expect(stop).toHaveBeenCalledOnce();
    expect(screen.queryByRole("meter")).not.toBeInTheDocument();
  });
  it("aborts a pending voice preview when the selected output changes", () => {
    api.getVoicePreview.mockReturnValue(new Promise(() => {}));
    const view = render(<AudioCheck outputDeviceId="first" />);
    fireEvent.click(screen.getByRole("button", { name: "Послушать Iris" }));
    const signal = api.getVoicePreview.mock.calls[0][0] as AbortSignal;
    view.rerender(<AudioCheck outputDeviceId="second" />);
    expect(signal.aborted).toBe(true);
    expect(screen.queryByRole("button", { name: "Остановить проверку" })).not.toBeInTheDocument();
  });
});

describe("attachment lifecycle", () => {
  it("cancels both transport and pending server upload and ignores its late result", async () => {
    const upload = deferred<unknown>();
    api.requestJson.mockImplementation((path: string, options?: RequestInit) => options?.method === "POST" ? upload.promise : Promise.resolve({ document: null }));
    const busy = vi.fn();
    render(<DocumentAttachment sessionId="session" onBusyChange={busy} />);
    await act(async () => {});
    fireEvent.change(screen.getByLabelText("Выбрать документ"), { target: { files: [new File(["test"], "note.md")] } });
    const [, options] = api.requestJson.mock.calls.find(([, init]) => init?.method === "POST")!;
    const uploadId = (options.body as FormData).get("upload_id") as string;
    fireEvent.click(screen.getByRole("button", { name: "Отменить чтение" }));
    expect(options.signal.aborted).toBe(true);
    expect(api.requestJson).toHaveBeenCalledWith(`/documents/${uploadId}?session_id=session`, { method: "DELETE" });
    await act(async () => upload.resolve({ id: uploadId, name: "note.md", fragment_count: 1, ephemeral: true }));
    expect(screen.queryByText("note.md")).not.toBeInTheDocument();
    expect(busy).toHaveBeenLastCalledWith(false);
  });
});

it("reschedules only after explicit Save, keeping the edited time local", async () => {
  const future = new Date(Date.now() + 86400_000).toISOString();
  reminders.getReminders.mockResolvedValue({ items: [{ id: "r", title: "Сборка", status: "open", due_at: future, delivery_token: "revision", delivered_at: null }] });
  reminders.updateReminder.mockResolvedValue({});
  render(<RemindersPanel plans={[]} onChanged={vi.fn()} />);
  fireEvent.click(await screen.findByText("Перенести", { selector: "summary" }));
  const input = await screen.findByLabelText("Перенести: Сборка");
  fireEvent.change(input, { target: { value: "2030-10-20T19:00" } });
  expect(reminders.updateReminder).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Сохранить срок" }));
  await waitFor(() => expect(reminders.updateReminder).toHaveBeenCalledWith("r", { due_at: new Date("2030-10-20T19:00").toISOString() }));
});

it("filters reminders as well as plans and honors every parent sort order", async () => {
  const rows = [
    { id: "a", title: "Alpha build", status: "open", due_at: "2030-12-01T12:00:00Z", created_at: "2026-10-01T12:00:00Z" },
    { id: "b", title: "Beta build", status: "open", due_at: "2030-11-01T12:00:00Z", created_at: "2026-10-02T12:00:00Z" },
  ];
  reminders.getReminders.mockResolvedValue({ items: rows });
  const view = render(<RemindersPanel plans={[]} onChanged={vi.fn()} sortOrder="alpha-asc" />);
  await screen.findByText("Alpha build");
  const titles = () => [...view.container.querySelectorAll("h3")].map(element => element.textContent);
  expect(titles()).toEqual(["Alpha build", "Beta build"]);
  for (const [sortOrder, expected] of [
    ["alpha-desc", ["Beta build", "Alpha build"]], ["date-asc", ["Alpha build", "Beta build"]], ["date-desc", ["Beta build", "Alpha build"]],
  ] as const) {
    view.rerender(<RemindersPanel plans={[]} onChanged={vi.fn()} sortOrder={sortOrder} />);
    expect(titles()).toEqual(expected);
  }
  view.rerender(<RemindersPanel plans={[]} onChanged={vi.fn()} query="Alpha" />);
  expect(titles()).toEqual(["Alpha build"]);
  view.rerender(<RemindersPanel plans={[]} onChanged={vi.fn()} query="" />);
  expect(titles()).toHaveLength(2);
});

it("explains unavailable ephemeral sources while preserving old saved source text", () => {
  const view = render(<DocumentSources value={{ name: "notes.txt", sources: [{ id: "D1", label: "стр. 2" }] }} />);
  expect(screen.getByText("D1 · стр. 2")).toBeInTheDocument();
  expect(screen.getByText(/Исходный текст не сохраняется в истории/)).toBeInTheDocument();
  view.rerender(<DocumentSources value={{ name: "old.txt", sources: [{ id: "D1", label: "стр. 1", text: "Старый исходный текст" }] }} />);
  expect(screen.getByText("Старый исходный текст")).toBeInTheDocument();
});

it("groups deleted and changed files and renders source text safely", () => {
  const patch = 'diff --git a/old.txt b/old.txt\n--- a/old.txt\n+++ /dev/null\n@@ -1 +0,0 @@\n-removed\ndiff --git a/new.ts b/new.ts\n--- a/new.ts\n+++ b/new.ts\n@@ -1 +1 @@\n-old\n+<script>alert(1)</script>\n';
  expect(splitPatch(patch).map(file => [file.name, file.added, file.removed])).toEqual([["old.txt", 0, 1], ["new.ts", 1, 1]]);
  const { container } = render(<PatchReview patch={patch} />);
  expect(container.querySelector("script")).toBeNull();
  expect(container.textContent).toContain("<script>alert(1)</script>");
});
