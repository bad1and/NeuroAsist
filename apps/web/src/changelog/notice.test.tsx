// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

beforeEach(() => { vi.resetModules(); localStorage.clear(); });
afterEach(() => { vi.restoreAllMocks(); });

async function setup() {
  const notices = await import("./notice");
  const { APP_VERSION } = await import("./catalog");
  const { notificationStore, notify } = await import("../notifications");
  return { ...notices, APP_VERSION, notificationStore, notify };
}

describe("уведомление об обновлении", () => {
  it("не имеет таймера, не дублируется при повторном подключении и переживает выход без прочтения", async () => {
    const api = await setup();
    const stop = api.watchChangelogNotice();
    expect(api.notificationStore.getSnapshot()).toEqual([expect.objectContaining({
      id: api.CHANGELOG_NOTICE_ID, duration: "persistent", navigateView: "changelog", navigateLabel: "Что нового",
    })]);
    stop();
    const stopAgain = api.watchChangelogNotice();
    expect(api.notificationStore.getSnapshot()).toHaveLength(1);
    stopAgain();
    api.notify.dismissAll(); // The process is gone; no active watcher acknowledges this.
    const afterRelaunch = api.watchChangelogNotice();
    expect(api.notificationStore.getSnapshot()).toHaveLength(1);
    expect(localStorage.getItem(api.CHANGELOG_STORAGE_KEY)).toBeNull();
    afterRelaunch();
  });

  it("считает ручное закрытие прочтением и не показывает ту же версию снова", async () => {
    const api = await setup();
    const stop = api.watchChangelogNotice();
    api.notify.dismiss(api.CHANGELOG_NOTICE_ID);
    expect(JSON.parse(localStorage.getItem(api.CHANGELOG_STORAGE_KEY)!)).toContain(api.APP_VERSION);
    stop();
    api.watchChangelogNotice()();
    expect(api.notificationStore.getSnapshot()).toHaveLength(0);
  });

  it("после перезапуска учитывает сохранённое прочтение; новая версия остаётся непрочитанной", async () => {
    const api = await setup();
    localStorage.setItem(api.CHANGELOG_STORAGE_KEY, JSON.stringify(["0.9.0"]));
    const stop = api.watchChangelogNotice();
    expect(api.notificationStore.getSnapshot()).toHaveLength(1);
    api.acknowledgeChangelog(); api.notify.dismiss(api.CHANGELOG_NOTICE_ID); stop();
    vi.resetModules();
    const relaunched = await setup();
    relaunched.watchChangelogNotice()();
    expect(relaunched.notificationStore.getSnapshot()).toHaveLength(0);
  });

  it("работает с повреждённым и недоступным хранилищем", async () => {
    const api = await setup();
    localStorage.setItem(api.CHANGELOG_STORAGE_KEY, "{broken");
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
    const stop = api.watchChangelogNotice();
    expect(api.notificationStore.getSnapshot()).toHaveLength(1);
    expect(() => api.notify.dismiss(api.CHANGELOG_NOTICE_ID)).not.toThrow();
    stop(); api.watchChangelogNotice()();
    expect(api.notificationStore.getSnapshot()).toHaveLength(0);
  });
});
