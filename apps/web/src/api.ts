import type {
  BackendEvent,
  ChatResponse,
  PublicSettings,
  StatusResponse,
  VoiceChatResponse,
  VoiceTtsStatusResponse,
} from "./types";

export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

export const WS_EVENTS_URL =
  import.meta.env.VITE_WS_EVENTS_URL ?? "ws://127.0.0.1:8000/ws/events";

async function requestJson<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string> | undefined),
  };

  if (options.body && !(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers,
    ...options,
  });

  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const payload = await response.json();
      if (typeof payload.detail === "string") {
        detail = payload.detail;
      }
    } catch {
      // Keep the status-only error.
    }
    throw new Error(detail);
  }

  return response.json() as Promise<T>;
}

export function getStatus(): Promise<StatusResponse> {
  return requestJson<StatusResponse>("/status");
}

export function getSettings(): Promise<PublicSettings> {
  return requestJson<PublicSettings>("/settings/public");
}

export function updateRuntimeSettings(payload: {
  model?: string;
  personality?: string;
  voice_language?: string;
  voice_tts_voice?: string;
}): Promise<PublicSettings> {
  return requestJson<PublicSettings>("/settings/runtime", {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function getEvents(limit = 100): Promise<{ events: BackendEvent[] }> {
  return requestJson<{ events: BackendEvent[] }>(`/events?limit=${limit}`);
}

export function getVoiceTtsStatus(
  voiceRequestId: string,
): Promise<VoiceTtsStatusResponse> {
  return requestJson<VoiceTtsStatusResponse>(`/voice/tts/${voiceRequestId}`);
}

export function sendChatMessage(
  sessionId: string,
  message: string,
): Promise<ChatResponse> {
  return requestJson<ChatResponse>("/chat", {
    method: "POST",
    body: JSON.stringify({
      session_id: sessionId,
      message,
    }),
  });
}

export async function sendVoiceMessage(
  sessionId: string,
  audio: Blob,
  language: string,
): Promise<VoiceChatResponse> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 90000);
  const form = new FormData();
  form.append("session_id", sessionId);
  form.append("language", language);
  form.append("audio", audio, "voice-message.webm");

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/voice/chat`, {
      method: "POST",
      body: form,
      signal: controller.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error("Voice request timed out");
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }

  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const payload = await response.json();
      if (typeof payload.detail === "string") {
        detail = payload.detail;
      }
    } catch {
      // Keep the status-only error.
    }
    throw new Error(detail);
  }

  return response.json() as Promise<VoiceChatResponse>;
}

export function resolveApiUrl(path: string): string {
  return path.startsWith("http") ? path : `${API_BASE_URL}${path}`;
}
