// @vitest-environment jsdom
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useRuntimeSettingsAutosave } from "./settingsAutosave";
import type { PublicSettings } from "./types";
const api = vi.hoisted(() => ({ updateRuntimeSettings: vi.fn() }));
vi.mock("./api", () => api);
const initial = { weather_enabled: true, news_enabled: true, voice_live_playback_prebuffer_ms: 0,
  voice_live_playback_prebuffer_segments: 1 } as PublicSettings;
function deferred() {
  let resolve!: (value: PublicSettings) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<PublicSettings>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
afterEach(() => { cleanup(); vi.useRealTimers(); });
beforeEach(() => {
  vi.resetAllMocks();
  api.updateRuntimeSettings.mockImplementation(async patch => ({ ...initial, ...patch }));
});
describe("очередь настроек", () => {
  it("не откатывает более новую правку после ошибки старого запроса", async () => {
    const first = deferred();
    const second = deferred();
    api.updateRuntimeSettings.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const applied = vi.fn();
    const { result } = renderHook(() => useRuntimeSettingsAutosave(vi.fn(), initial, applied));
    act(() => { void result.current.save({ weather_enabled: false }); });
    act(() => { void result.current.save({ weather_enabled: true }); });
    await act(async () => { first.reject(new Error("offline")); });
    expect(applied).not.toHaveBeenCalled();
    expect(api.updateRuntimeSettings).toHaveBeenCalledTimes(2);
    await act(async () => { second.resolve(initial); });
    expect(applied).toHaveBeenCalledExactlyOnceWith(initial, ["weather_enabled"]);
    expect(result.current.status).toBe("saved");
  });
  it("не применяет старый успешный ответ поверх нового изменения", async () => {
    const first = deferred();
    const second = deferred();
    api.updateRuntimeSettings.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const applied = vi.fn();
    const { result } = renderHook(() => useRuntimeSettingsAutosave(vi.fn(), initial, applied));
    act(() => { void result.current.save({ weather_enabled: false }); });
    act(() => { void result.current.save({ weather_enabled: true }); });
    await act(async () => { first.resolve({ ...initial, weather_enabled: false }); });
    expect(applied).not.toHaveBeenCalled();
    await act(async () => { second.resolve(initial); });
    expect(applied).toHaveBeenCalledExactlyOnceWith(initial, ["weather_enabled"]);
  });
  it("сохраняет оба отложенных поля и оставляет последнее значение каждого", async () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useRuntimeSettingsAutosave(vi.fn(), initial));
    act(() => {
      void result.current.save({ voice_live_playback_prebuffer_segments: 2 }, undefined, undefined, 300);
      void result.current.save({ voice_live_playback_prebuffer_ms: 500 }, undefined, undefined, 300);
      void result.current.save({ voice_live_playback_prebuffer_segments: 3 }, undefined, undefined, 300);
    });
    expect(api.updateRuntimeSettings).not.toHaveBeenCalled();
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });
    const patches = api.updateRuntimeSettings.mock.calls.map(([patch]) => patch);
    expect(Object.assign({}, ...patches)).toEqual({ voice_live_playback_prebuffer_segments: 3, voice_live_playback_prebuffer_ms: 500 });
    expect(patches.every(patch => patch.voice_live_playback_prebuffer_segments !== 2)).toBe(true);
  });
  it("отправляет отложенную правку при выходе", async () => {
    vi.useFakeTimers();
    const { result, unmount } = renderHook(() => useRuntimeSettingsAutosave(vi.fn(), initial));
    act(() => { void result.current.save({ voice_live_playback_prebuffer_ms: 700 }, undefined, undefined, 300); });
    unmount();
    expect(api.updateRuntimeSettings).toHaveBeenCalledExactlyOnceWith({ voice_live_playback_prebuffer_ms: 700 });
    await act(async () => { await vi.runAllTimersAsync(); });
    expect(api.updateRuntimeSettings).toHaveBeenCalledOnce();
  });
  it("сохраняет ошибку одного поля после успешного сохранения другого и применяет повтор", async () => {
    api.updateRuntimeSettings.mockRejectedValueOnce(new Error("offline"));
    const applied = vi.fn();
    const committed = vi.fn();
    const { result } = renderHook(() => useRuntimeSettingsAutosave(vi.fn(), initial, applied));
    await act(async () => { await result.current.save({ weather_enabled: false }, undefined, committed); });
    expect(applied).toHaveBeenCalledWith(initial, ["weather_enabled"]);
    await act(async () => { await result.current.save({ news_enabled: false }); });
    expect(result.current.status).toBe("error");
    act(() => { result.current.retry(); });
    await waitFor(() => expect(result.current.status).toBe("saved"));
    expect(committed).toHaveBeenCalledOnce();
    expect(applied).toHaveBeenLastCalledWith(expect.objectContaining({ weather_enabled: false }), ["weather_enabled"]);
  });
});
