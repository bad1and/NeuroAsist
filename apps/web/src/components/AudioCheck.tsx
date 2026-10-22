import { useEffect, useRef, useState } from "react";
import { createTimer } from "animejs";
import { MaterialButton } from "./MaterialButton";
import { getVoicePreview } from "../api";
import { setAudioElementOutput } from "../audio-devices";

export function AudioCheck({ inputDeviceId = "", outputDeviceId = "", playbackRate = 1 }: {
  inputDeviceId?: string; outputDeviceId?: string; playbackRate?: number;
}) {
  const [recording, setRecording] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [level, setLevel] = useState(0);
  const [error, setError] = useState("");
  const resources = useRef<{ stream?: MediaStream; context?: AudioContext; timer?: ReturnType<typeof createTimer>; audio?: HTMLAudioElement; url?: string; abort?: AbortController }>({});
  const generation = useRef(0);
  const stop = (updateState = true) => {
    generation.current++;
    const current = resources.current;
    resources.current = {};
    current.timer?.cancel();
    current.stream?.getTracks().forEach(track => track.stop());
    void current.context?.close().catch(() => {});
    current.abort?.abort();
    current.audio?.pause();
    if (current.audio) { current.audio.onended = null; current.audio.onerror = null; }
    if (current.url) URL.revokeObjectURL(current.url);
    if (updateState) { setRecording(false); setPreviewing(false); setLevel(0); }
  };
  useEffect(() => { stop(); return () => stop(false); }, [inputDeviceId, outputDeviceId]);
  const microphone = async () => {
    stop(); setError(""); setRecording(true);
    const token = generation.current;
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error("Проверка микрофона недоступна в этом окне");
      const stream = await navigator.mediaDevices.getUserMedia({ audio: inputDeviceId ? { deviceId: { exact: inputDeviceId } } : true, video: false });
      if (token !== generation.current) { stream.getTracks().forEach(track => track.stop()); return; }
      resources.current.stream = stream;
      const context = new AudioContext();
      resources.current.context = context;
      const analyser = context.createAnalyser(); analyser.fftSize = 256;
      context.createMediaStreamSource(stream).connect(analyser);
      await context.resume();
      if (token !== generation.current) return;
      const buffer = new Uint8Array(analyser.fftSize);
      let updated = 0;
      resources.current.timer = createTimer({ duration: 15_000, onUpdate: () => {
        if (performance.now() - updated < 80) return;
        updated = performance.now(); analyser.getByteTimeDomainData(buffer);
        const rms = Math.sqrt(buffer.reduce((sum, sample) => sum + ((sample - 128) / 128) ** 2, 0) / buffer.length);
        setLevel(Math.min(1, rms * 5));
      }, onComplete: () => stop() });
    } catch (cause) { if (token === generation.current) { stop(); setError(cause instanceof Error ? cause.message : "Не удалось включить микрофон"); } }
  };
  const preview = async () => {
    stop(); setError(""); setPreviewing(true);
    const token = generation.current;
    const abort = new AbortController(); resources.current.abort = abort;
    try {
      const blob = await getVoicePreview(abort.signal);
      if (token !== generation.current) return;
      const url = URL.createObjectURL(blob); resources.current.url = url;
      const audio = new Audio(url); resources.current.audio = audio;
      audio.playbackRate = playbackRate;
      await setAudioElementOutput(audio, outputDeviceId);
      if (token !== generation.current) return;
      audio.onended = () => stop();
      audio.onerror = () => { stop(); setError("Не удалось воспроизвести пробную фразу"); };
      await audio.play();
    } catch (cause) { if (token === generation.current) { stop(); setError(cause instanceof Error ? cause.message : "Не удалось проверить голос"); } }
  };
  return <section className="audio-check" aria-label="Проверка микрофона и звука">
    <div className="audio-check-actions">
      <MaterialButton materialKey="audio.check-input" className="secondary" type="button" disabled={recording || previewing} onClick={() => void microphone()}>Проверить микрофон</MaterialButton>
      <MaterialButton materialKey="audio.preview" className="secondary" type="button" disabled={recording || previewing} onClick={() => void preview()}>Послушать Iris</MaterialButton>
      {(recording || previewing) && <MaterialButton materialKey="audio.stop-check" className="text-button" type="button" onClick={() => stop()}>Остановить проверку</MaterialButton>}
    </div>
    {recording && <><meter min={0} max={1} value={level} aria-label="Уровень микрофона" /><p role="status">Скажите несколько слов. Проверка длится до 15 секунд; запись не сохраняется.</p></>}
    {previewing && <p role="status">Проверяем голос Iris…</p>}
    {error && <p className="error-text" role="alert">{error}</p>}
  </section>;
}
