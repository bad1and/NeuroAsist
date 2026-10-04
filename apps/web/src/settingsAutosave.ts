import { useCallback, useEffect, useRef, useState } from "react";
import { updateRuntimeSettings } from "./api";
import type { PublicSettings } from "./types";

export type RuntimeSettingsPatch = Parameters<typeof updateRuntimeSettings>[0];
export type AutoSaveStatus = "idle" | "saving" | "saved" | "error";
type Field = keyof RuntimeSettingsPatch;
type Entry = {
  patch: RuntimeSettingsPatch;
  versions: Partial<Record<Field, number>>;
  rollback?: () => void;
  committed?: (settings: PublicSettings) => void;
  resolve: (saved: boolean) => void;
  timer?: ReturnType<typeof setTimeout>;
};

/** Serial writes, with field revisions protecting newer edits from old replies. */
export function useRuntimeSettingsAutosave(
  onSettingsChanged: (settings: PublicSettings) => void,
  settings?: PublicSettings | null,
  onApplied?: (settings: PublicSettings, fields: Field[]) => void,
) {
  const callbacks = useRef({ onSettingsChanged, onApplied });
  callbacks.current = { onSettingsChanged, onApplied };
  const confirmed = useRef(settings);
  if (!confirmed.current && settings) confirmed.current = settings;
  const versions = useRef<Partial<Record<Field, number>>>({});
  const pending = useRef<Entry[]>([]);
  const delayed = useRef(new Map<Field, Entry>());
  const failed = useRef(new Map<Field, Entry>());
  const running = useRef(false);
  const [status, setStatus] = useState<AutoSaveStatus>("idle");

  const drain = useCallback(async () => {
    if (running.current || !pending.current.length) return;
    running.current = true;
    while (pending.current.length) {
      const entries = pending.current.splice(0);
      const patch = Object.assign({}, ...entries.map(entry => entry.patch)) as RuntimeSettingsPatch;
      setStatus("saving");
      try {
        const next = await updateRuntimeSettings(patch);
        confirmed.current = next;
        callbacks.current.onSettingsChanged(next);
        for (const entry of entries) {
          const fields = (Object.keys(entry.patch) as Field[]).filter(field =>
            entry.versions[field] === versions.current[field]);
          fields.forEach(field => failed.current.delete(field));
          if (fields.length) {
            callbacks.current.onApplied?.(next, fields);
            entry.committed?.(next);
          }
          entry.resolve(fields.length > 0);
        }
      } catch {
        for (const entry of entries) {
          const fields = (Object.keys(entry.patch) as Field[]).filter(field =>
            entry.versions[field] === versions.current[field]);
          fields.forEach(field => failed.current.set(field, entry));
          if (fields.length) {
            if (confirmed.current && callbacks.current.onApplied) {
              callbacks.current.onApplied(confirmed.current, fields);
            } else entry.rollback?.();
          }
          entry.resolve(false);
        }
      }
    }
    running.current = false;
    setStatus(failed.current.size ? "error" : delayed.current.size ? "saving" : "saved");
  }, []);

  const save = useCallback((patch: RuntimeSettingsPatch, rollback?: () => void,
    committed?: (settings: PublicSettings) => void, delay = 0): Promise<boolean> => {
    const fields = Object.keys(patch) as Field[];
    if (!fields.length) return Promise.resolve(true);
    return new Promise(resolve => {
      const entry: Entry = { patch, rollback, committed, resolve, versions: {} };
      fields.forEach(field => {
        entry.versions[field] = versions.current[field] = (versions.current[field] ?? 0) + 1;
        failed.current.delete(field);
        const old = delayed.current.get(field);
        if (old) {
          clearTimeout(old.timer);
          delayed.current.delete(field);
          old.resolve(false);
        }
      });
      setStatus("saving");
      if (delay && fields.length === 1) {
        const field = fields[0];
        delayed.current.set(field, entry);
        entry.timer = setTimeout(() => {
          delayed.current.delete(field);
          pending.current.push(entry);
          void drain();
        }, delay);
      } else {
        pending.current.push(entry);
        void drain();
      }
    });
  }, [drain]);

  const retry = useCallback(() => {
    const entries = [...new Set(failed.current.values())];
    for (const entry of entries) {
      const patch = Object.fromEntries(Object.entries(entry.patch).filter(([field]) =>
        failed.current.get(field as Field) === entry)) as RuntimeSettingsPatch;
      void save(patch, entry.rollback, entry.committed);
    }
  }, [save]);

  const flush = useCallback(() => {
    for (const entry of delayed.current.values()) {
      clearTimeout(entry.timer);
      pending.current.push(entry);
    }
    delayed.current.clear();
    void drain();
  }, [drain]);
  useEffect(() => flush, [flush]);
  return { save, retry, flush, status };
}
