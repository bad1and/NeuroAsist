import { useEffect, useRef } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { isDesktopApp } from "./desktop";
import type { VoiceState } from "./types";

export type DesktopConversationSnapshot = {
  session_id: string | null; ready: boolean; loading: boolean; document_busy: boolean;
  microphone_active: boolean; microphone_starting: boolean; sound_muted: boolean;
  voice_state: VoiceState; cue: string; error: string | null;
};
export type DesktopConversationCommand = {
  id: string; type: "snapshot" | "microphone" | "sound" | "send" | "attachment_busy" | "attachment_changed";
  session_id: string | null; text?: string; busy?: boolean;
};
export const DOCUMENT_CHANGED = "iris-document-changed";

/** The main WebView remains the sole microphone, playback and conversation owner. */
export function useDesktopConversationBridge(snapshot: DesktopConversationSnapshot,
  execute: (command: DesktopConversationCommand) => Promise<void>) {
  const current = useRef({ snapshot, execute });
  current.current = { snapshot, execute };
  useEffect(() => {
    if (!isDesktopApp()) return;
    let disposed = false;
    const seen = new Set<string>();
    const unlisten = listen<DesktopConversationCommand>("desktop-avatar-command", async ({ payload: command }) => {
      if (disposed || seen.has(command.id)) return;
      seen.add(command.id);
      if (seen.size > 128) seen.delete(seen.values().next().value!);
      try {
        if (command.type !== "snapshot" && command.session_id !== current.current.snapshot.session_id)
          throw new Error("Диалог изменился. Отправьте сообщение заново.");
        if (command.type !== "snapshot") await current.current.execute(command);
        await invoke("desktop_avatar_snapshot", { snapshot: { ...current.current.snapshot, ack: command.id } });
      } catch (error) {
        await invoke("desktop_avatar_snapshot", { snapshot: { ...current.current.snapshot, ack: command.id,
          command_error: error instanceof Error ? error.message : "Не удалось выполнить действие" } });
      }
    });
    return () => { disposed = true; void unlisten.then(stop => stop()); };
  }, []);
  useEffect(() => {
    if (isDesktopApp()) void invoke("desktop_avatar_snapshot", { snapshot }).catch(() => {});
  }, [snapshot.session_id, snapshot.ready, snapshot.loading, snapshot.document_busy,
    snapshot.microphone_active, snapshot.microphone_starting, snapshot.sound_muted,
    snapshot.voice_state, snapshot.cue, snapshot.error]);
}
