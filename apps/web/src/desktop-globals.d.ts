interface Window {
  __NEUROASIST_DESKTOP_CONFIG__?: {
    apiBaseUrl: string;
    apiToken: string;
    wsEventsUrl: string;
    safeMode: boolean;
  };
  __TAURI_INTERNALS__?: {
    invoke<T>(command: string, args?: Record<string, unknown>): Promise<T>;
  };
}
