import { Disclosure } from "./Disclosure";
import { useEffect, useRef, useState } from "react";
import { cancelCodingImage, getCodingImage, getSettings, prepareCodingImage, registerCodingProject, updateRuntimeSettings, type CodingImageState } from "../api";
import { chooseCodingProject, isDesktopApp } from "../desktop";
import type { PublicSettings } from "../types";
import { notify } from "../notifications";
import { MaterialButton } from "./MaterialButton";

export function CodingSetup({ onSettingsChanged, onProjectRegistered, includeImage = false }:
  { onSettingsChanged: (settings: PublicSettings) => void; onProjectRegistered: (path: string) => void; includeImage?: boolean }) {
  const connectionFailed = useRef(false);
  const [state, setState] = useState<CodingImageState>({ status: "idle", output: "", error: null });
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!includeImage) return;
    let stopped = false; let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try { const next = await getCodingImage(); if (!stopped) { setState(next); connectionFailed.current = false; } } catch (error) { if (!stopped && !connectionFailed.current) { connectionFailed.current = true; notify.error("Coding Agent", String(error), { id: "coding.setup" }); } }
      if (!stopped) timer = setTimeout(() => void poll(), 1500);
    };
    void poll(); return () => { stopped = true; clearTimeout(timer); };
  }, [includeImage]);
  const choose = async () => {
    setBusy(true);
    try {
      const path = await chooseCodingProject();
      if (path) { await registerCodingProject(path); await updateRuntimeSettings({ coding_project_root: path }); onSettingsChanged(await getSettings()); onProjectRegistered(path); }
    } catch (error) { notify.error("Coding Agent", String(error), { id: "coding.setup" }); } finally { setBusy(false); }
  };
  const prepare = async (cancel = false) => {
    setBusy(true);
    try { setState(await (cancel ? cancelCodingImage() : prepareCodingImage())); }
    catch (error) { notify.error("Coding Agent", String(error), { id: "coding.setup" }); } finally { setBusy(false); }
  };
  return <div className="coding-card">
    <MaterialButton materialKey="CodingSetup.1" className="secondary" disabled={busy || !isDesktopApp()} onClick={() => void choose()}>Добавить проект</MaterialButton>
    {!isDesktopApp() && <p>Выбор проекта доступен в настольном приложении.</p>}
    {includeImage && <>
      <p>Docker устанавливается отдельно. Для подготовки песочницы потребуется интернет.</p>
      <MaterialButton materialKey="CodingSetup.2" className="secondary" disabled={busy} onClick={() => void prepare(state.status === "preparing")}>
        {state.status === "preparing" ? "Отменить подготовку" : state.status === "failed" || state.status === "cancelled" ? "Повторить подготовку" : "Подготовить песочницу"}
      </MaterialButton>
      {state.status === "ready" && <p role="status">Песочница подготовлена. Обновите состояние Docker.</p>}
      {state.output && <Disclosure materialKey="coding.setup.log" label={<>Журнал подготовки</>}><pre data-i18n-skip style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", maxHeight: 220, overflow: "auto" }}>{state.output}</pre></Disclosure>}
    </>}
    {state.error && <p className="notice" role="alert">{state.error}</p>}
  </div>;
}
