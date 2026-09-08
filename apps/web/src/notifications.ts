import { useSyncExternalStore } from "react";

export type NotificationType = "error" | "warning" | "success" | "info" | "reminder";

export interface NotificationAction {
  label: string;
  onClick: () => void;
  variant?: "primary" | "secondary";
}

export interface AppNotification {
  id: string;
  type: NotificationType;
  title: string;
  message: string;
  details?: string;
  actions?: NotificationAction[];
  navigateView?: string;
  duration?: number | "persistent";
  createdAt: number;
}

export interface NotificationOptions {
  id?: string;
  details?: string;
  actions?: NotificationAction[];
  navigateView?: string;
  duration?: number | "persistent";
}

export const DEFAULT_DURATIONS: Record<NotificationType, number | "persistent"> = {
  success: 4500,
  info: 4500,
  warning: 8000,
  error: "persistent",
  reminder: "persistent",
};

type Listener = () => void;

const NOTIFICATION_SYNC_CHANNEL = "iris_notification_sync_bus";

class NotificationStore {
  private notifications: AppNotification[] = [];
  private listeners = new Set<Listener>();
  private channel: BroadcastChannel | null = null;

  constructor() {
    if (typeof window !== "undefined" && typeof BroadcastChannel !== "undefined") {
      try {
        this.channel = new BroadcastChannel(NOTIFICATION_SYNC_CHANNEL);
        this.channel.onmessage = (e) => {
          const msg = e.data;
          if (!msg || typeof msg !== "object") return;
          if (msg.type === "show" && msg.notification) {
            this.handleSyncShow(msg.notification);
          } else if (msg.type === "dismiss" && msg.id) {
            this.handleSyncDismiss(msg.id);
          } else if (msg.type === "dismissAll") {
            this.handleSyncDismissAll();
          }
        };
      } catch {
        // BroadcastChannel unavailable in this context
      }
    }
  }

  private handleSyncShow(full: AppNotification): void {
    const existingIndex = this.notifications.findIndex(
      (n) => n.id === full.id || (n.title === full.title && n.message === full.message && n.type === full.type)
    );

    if (existingIndex >= 0) {
      const next = [...this.notifications];
      next.splice(existingIndex, 1);
      this.notifications = [full, ...next];
    } else {
      this.notifications = [full, ...this.notifications];
    }

    this.emitChange();
  }

  private handleSyncDismiss(id: string): void {
    const next = this.notifications.filter((n) => n.id !== id);
    if (next.length !== this.notifications.length) {
      this.notifications = next;
      this.emitChange();
    }
  }

  private handleSyncDismissAll(): void {
    if (this.notifications.length > 0) {
      this.notifications = [];
      this.emitChange();
    }
  }

  private emitChange(): void {
    for (const listener of this.listeners) {
      listener();
    }
  }

  subscribe = (listener: Listener): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  getSnapshot = (): AppNotification[] => {
    return this.notifications;
  };

  show = (notification: Omit<AppNotification, "id" | "createdAt"> & { id?: string; createdAt?: number }): string => {
    const id = notification.id || `notif-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    const full: AppNotification = {
      ...notification,
      id,
      duration: notification.duration ?? DEFAULT_DURATIONS[notification.type],
      createdAt: notification.createdAt ?? Date.now(),
    };

    // If notification with the same ID or same title+message exists, replace it or bump it to top
    const existingIndex = this.notifications.findIndex(
      (n) => n.id === id || (n.title === full.title && n.message === full.message && n.type === full.type)
    );

    if (existingIndex >= 0) {
      const next = [...this.notifications];
      next.splice(existingIndex, 1);
      this.notifications = [full, ...next];
    } else {
      this.notifications = [full, ...this.notifications];
    }

    this.emitChange();

    try {
      this.channel?.postMessage({
        type: "show",
        notification: {
          id: full.id,
          type: full.type,
          title: full.title,
          message: full.message,
          details: full.details,
          navigateView: full.navigateView,
          duration: full.duration,
          createdAt: full.createdAt,
        },
      });
    } catch {
      // Ignore broadcast errors
    }

    return id;
  };

  error = (title: string, message: string, options?: NotificationOptions): string => {
    return this.show({
      type: "error",
      title,
      message,
      ...options,
    });
  };

  warning = (title: string, message: string, options?: NotificationOptions): string => {
    return this.show({
      type: "warning",
      title,
      message,
      ...options,
    });
  };

  success = (title: string, message: string, options?: NotificationOptions): string => {
    return this.show({
      type: "success",
      title,
      message,
      ...options,
    });
  };

  info = (title: string, message: string, options?: NotificationOptions): string => {
    return this.show({
      type: "info",
      title,
      message,
      ...options,
    });
  };

  reminder = (title: string, message: string, options?: NotificationOptions): string => {
    return this.show({
      type: "reminder",
      title,
      message,
      ...options,
    });
  };

  dismiss = (id: string): void => {
    const next = this.notifications.filter((n) => n.id !== id);
    if (next.length !== this.notifications.length) {
      this.notifications = next;
      this.emitChange();
    }
    try {
      this.channel?.postMessage({ type: "dismiss", id });
    } catch {}
  };

  dismissAll = (): void => {
    if (this.notifications.length > 0) {
      this.notifications = [];
      this.emitChange();
    }
    try {
      this.channel?.postMessage({ type: "dismissAll" });
    } catch {}
  };
}

export const notificationStore = new NotificationStore();

export const notify = {
  show: notificationStore.show,
  error: notificationStore.error,
  warning: notificationStore.warning,
  success: notificationStore.success,
  info: notificationStore.info,
  reminder: notificationStore.reminder,
  dismiss: notificationStore.dismiss,
  dismissAll: notificationStore.dismissAll,
};

export function useNotifications(): AppNotification[] {
  return useSyncExternalStore(notificationStore.subscribe, notificationStore.getSnapshot);
}
