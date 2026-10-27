import { notificationStore, notify } from "../notifications";
import { APP_VERSION, currentRelease } from "./catalog";

export const CHANGELOG_STORAGE_KEY = "iris.changelog.acknowledged.v1";
export const CHANGELOG_NOTICE_ID = `changelog.${APP_VERSION}`;
const sessionAcknowledged = new Set<string>();

function readAcknowledged(): string[] {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(CHANGELOG_STORAGE_KEY) ?? "[]");
    return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
  } catch { return []; }
}

export function acknowledgeChangelog(version = APP_VERSION): void {
  sessionAcknowledged.add(version);
  try {
    localStorage.setItem(CHANGELOG_STORAGE_KEY, JSON.stringify([...new Set([...readAcknowledged(), version])]));
  } catch { /* Blocked storage: remember the action for this session. */ }
}

/** A launch alone never acknowledges a release: closing the app leaves it unread. */
export function watchChangelogNotice(): () => void {
  if (sessionAcknowledged.has(APP_VERSION) || readAcknowledged().includes(APP_VERSION)) return () => {};
  notify.info(`Что нового в Iris · ${APP_VERSION}`, currentRelease.summary, {
    id: CHANGELOG_NOTICE_ID, duration: "persistent", navigateView: "changelog", navigateLabel: "Что нового",
  });
  const stop = notificationStore.subscribe(() => {
    if (!notificationStore.getSnapshot().some(item => item.id === CHANGELOG_NOTICE_ID)) acknowledgeChangelog();
  });
  return stop;
}

export function openChangelog(): void {
  window.dispatchEvent(new Event("iris-open-changelog"));
}
