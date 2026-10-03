// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createRef, useEffect } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { notify } from "../notifications";
import { AppDialog } from "./AppDialog";
import { ConversationSurface } from "./ConversationSurface";
import { NotificationHost } from "./NotificationHost";

afterEach(() => {
  cleanup();
  notify.dismissAll();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("reserves the measured confirmation height through resizing and exit, then releases it", async () => {
  vi.useFakeTimers();
  let height = 180;
  const resizes: (() => void)[] = [];
  const disconnect = vi.fn();
  vi.stubGlobal("ResizeObserver", class {
    constructor(callback: (entries: ResizeObserverEntry[]) => void) { resizes.push(() => callback([])); }
    observe() {}
    unobserve() {}
    disconnect = disconnect;
  });
  vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockImplementation(function (this: HTMLElement) {
    return this.matches(".app-dialog-host") ? height : 0;
  });
  const backgroundHost = createRef<HTMLDivElement>();
  const view = (open: boolean) => <>
    <NotificationHost pinnedContentRef={backgroundHost} />
    <AppDialog open={open} title="Очистить память?" onClose={() => {}} />
  </>;
  const rendered = render(view(false));
  const host = screen.getByRole("complementary", { name: "Уведомления приложения" });
  expect(host.style.getPropertyValue("--notification-dialog-offset")).toBe("0px");
  await act(async () => { rendered.rerender(view(true)); });
  expect(host.style.getPropertyValue("--notification-dialog-offset")).toBe("188px");
  height = 310;
  act(() => resizes.forEach((resize) => resize()));
  expect(host.style.getPropertyValue("--notification-dialog-offset")).toBe("318px");
  await act(async () => { rendered.rerender(view(false)); });
  expect(host.style.getPropertyValue("--notification-dialog-offset")).toBe("318px");
  await act(async () => { vi.advanceTimersByTime(190); });
  expect(screen.queryByRole("alertdialog")).toBeNull();
  expect(host.style.getPropertyValue("--notification-dialog-offset")).toBe("0px");
  rendered.unmount();
  expect(disconnect).toHaveBeenCalled();
});

it("reserves an existing dialog when the first notification mounts the host", async () => {
  vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockImplementation(function (this: HTMLElement) {
    return this.matches(".app-dialog-host") ? 250 : 0;
  });
  render(<><NotificationHost /><AppDialog open title="Подтверждение" onClose={() => {}} /></>);
  expect(screen.queryByRole("complementary", { name: "Уведомления приложения" })).toBeNull();
  await act(async () => { notify.info("Загрузка", "Подготовка", { duration: "persistent" }); });
  expect(screen.getByRole("complementary", { name: "Уведомления приложения" }).style.getPropertyValue("--notification-dialog-offset")).toBe("258px");
});

it("moves notifications above the live conversation without remounting its controls", async () => {
  const backgroundHost = createRef<HTMLDivElement>();
  const mounted = vi.fn();
  const unmounted = vi.fn();
  function Controls() {
    useEffect(() => { mounted(); return unmounted; }, []);
    return <input aria-label="Сообщение Ирис" defaultValue="" />;
  }
  await act(async () => { render(<>
    <ConversationSurface active={false} backgroundVisible backgroundHost={backgroundHost}><Controls /></ConversationSurface>
    <NotificationHost pinnedContentRef={backgroundHost} />
  </>); });
  const slot = backgroundHost.current;
  const input = screen.getByRole("textbox");
  fireEvent.change(input, { target: { value: "Продолжаем разговор" } });
  await act(async () => { notify.info("Уведомление", "Новое событие", { duration: "persistent" }); });
  const host = screen.getByRole("complementary");
  expect(host.lastElementChild).toBe(slot);
  expect(host.firstElementChild!.contains(screen.getByText("Новое событие"))).toBe(true);
  await act(async () => { notify.dismissAll(); });
  expect(backgroundHost.current).toBe(slot);
  expect(screen.getByRole("textbox")).toBe(input);
  expect((input as HTMLInputElement).value).toBe("Продолжаем разговор");
  expect(mounted).toHaveBeenCalledTimes(1);
  expect(unmounted).not.toHaveBeenCalled();
});
