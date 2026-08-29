import { CustomSelect } from "./components/CustomSelect";
import { useEffect, useRef, useState } from "react";
import {
  IconInterfaceSecurityShield4,
  IconInterfaceSpirals,
  IconInterfaceTimeStopWatchCircle,
  IconInterfaceDownloadBox1,
  IconInterfaceFavoriteLike1,
} from "./CustomIcons";
import { FigmaMicIcon } from "./FigmaIcons";

import { BrowserVadRecorder, type CaptureMetadata, type MicrophoneProfile } from "./vad";

type Scenario = {
  id: string;
  title: string;
  reference: string;
  tags: string[];
  noiseOnly?: boolean;
};

type SavedCapture = {
  id: string;
  scenarioId: string;
  reference: string;
  tags: string[];
  profile: MicrophoneProfile;
  noiseOnly: boolean;
  sessionSequence: number;
  createdAt: string;
  metadata: CaptureMetadata;
  audio: Blob;
};

type CaptureMessage = {
  text: string;
  tone: "error" | "success";
};

const SCENARIOS: Scenario[] = [
  { id: "normal", title: "Обычная речь", reference: "Привет Iris, как у тебя дела?", tags: ["normal"] },
  { id: "fast", title: "Быстрая речь", reference: "Давай быстро проверим распознавание длинной фразы без лишних пауз", tags: ["fast"] },
  { id: "quiet", title: "Тихая речь", reference: "Я говорю тихо, но окончание фразы должно сохраниться", tags: ["quiet", "quiet-ending"] },
  { id: "yes", title: "Короткое «Да»", reference: "Да", tags: ["short"] },
  { id: "no", title: "Короткое «Нет»", reference: "Нет", tags: ["short"] },
  { id: "well", title: "Короткое «Ну»", reference: "Ну", tags: ["short"] },
  { id: "what", title: "Короткое «Что?»", reference: "Что?", tags: ["short"] },
  { id: "pause", title: "Пауза внутри фразы", reference: "Я начну фразу, сделаю паузу и затем спокойно её закончу", tags: ["pause"] },
  { id: "unfinished", title: "Незаконченная фраза", reference: "Мне кажется, что если", tags: ["unfinished"] },
  { id: "terms-1", title: "Термины: Iris и NeuroAsist", reference: "Iris работает в проекте NeuroAsist", tags: ["terms"] },
  { id: "terms-2", title: "Термины: GigaAM и DeepSeek", reference: "GigaAM и DeepSeek подключены к NeuroAsist", tags: ["terms"] },
  { id: "terms-3", title: "Термины: ComfyUI и GitHub", reference: "Открой ComfyUI и GitHub", tags: ["terms"] },
  { id: "keyboard", title: "Шум клавиатуры", reference: "", tags: ["keyboard", "noise"], noiseOnly: true },
  { id: "fan", title: "Шум вентилятора", reference: "", tags: ["fan", "noise"], noiseOnly: true },
  { id: "headset", title: "Микрофон гарнитуры", reference: "Проверка микрофона гарнитуры", tags: ["headset"] },
  { id: "speakers", title: "Колонки и эхоподавление", reference: "Проверка колонок и эхоподавления", tags: ["speakers", "aec"] },
  { id: "soft-tail", title: "Тихое окончание", reference: "Пожалуйста, не обрезай последнее тихое слово", tags: ["quiet-ending"] },
  { id: "live-1", title: "Живой диалог · начало", reference: "Расскажи коротко, что ты умеешь", tags: ["live", "sequence"] },
  { id: "live-2", title: "Живой диалог · продолжение", reference: "А теперь продолжи предыдущую мысль", tags: ["live", "sequence"] },
  { id: "live-3", title: "Живой диалог · завершение", reference: "Спасибо, этого достаточно", tags: ["live", "sequence", "short"] },
];

const DB_NAME = "neuroasist-private-stt-capture";
const STORE_NAME = "captures";

function openDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE_NAME, { keyPath: "id" });
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function saveCapture(capture: SavedCapture): Promise<void> {
  const database = await openDatabase();
  await new Promise<void>((resolve, reject) => {
    const transaction = database.transaction(STORE_NAME, "readwrite");
    transaction.objectStore(STORE_NAME).put(capture);
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error);
  });
  database.close();
}

async function listCaptures(): Promise<SavedCapture[]> {
  const database = await openDatabase();
  const captures = await new Promise<SavedCapture[]>((resolve, reject) => {
    const request = database.transaction(STORE_NAME).objectStore(STORE_NAME).getAll();
    request.onsuccess = () => resolve(request.result as SavedCapture[]);
    request.onerror = () => reject(request.error);
  });
  database.close();
  return captures.sort((left, right) => left.sessionSequence - right.sessionSequence);
}

function encodeWav(chunks: ArrayBuffer[], sampleRate: number): Blob {
  const byteLength = chunks.reduce((total, chunk) => total + chunk.byteLength, 0);
  const buffer = new ArrayBuffer(44 + byteLength);
  const view = new DataView(buffer);
  const write = (offset: number, value: string) => {
    for (let index = 0; index < value.length; index += 1) view.setUint8(offset + index, value.charCodeAt(index));
  };
  write(0, "RIFF");
  view.setUint32(4, 36 + byteLength, true);
  write(8, "WAVEfmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  write(36, "data");
  view.setUint32(40, byteLength, true);
  const output = new Uint8Array(buffer, 44);
  let offset = 0;
  for (const chunk of chunks) {
    output.set(new Uint8Array(chunk), offset);
    offset += chunk.byteLength;
  }
  return new Blob([buffer], { type: "audio/wav" });
}

function download(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function GuidedSttCapture({
  profile,
  inputDeviceId = "",
}: {
  profile: MicrophoneProfile;
  inputDeviceId?: string;
}) {
  const recorder = useRef<BrowserVadRecorder | null>(null);
  const chunks = useRef<ArrayBuffer[]>([]);
  const metadata = useRef<CaptureMetadata | null>(null);
  const [captures, setCaptures] = useState<SavedCapture[]>([]);
  const [scenarioIndex, setScenarioIndex] = useState(0);
  const [reference, setReference] = useState(SCENARIOS[0].reference);
  const [recording, setRecording] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<CaptureMessage | null>(null);
  const completedScenarioIds = new Set(captures.map((capture) => capture.scenarioId));
  const completedCount = completedScenarioIds.size;
  const progress = Math.min(100, (completedCount / SCENARIOS.length) * 100);

  useEffect(() => {
    void listCaptures()
      .then(setCaptures)
      .catch(() => setMessage({ text: "Локальное хранилище записей недоступно.", tone: "error" }));
    return () => recorder.current?.stop();
  }, []);

  const scenario = SCENARIOS[scenarioIndex];
  const selectScenario = (index: number) => {
    setScenarioIndex(index);
    setReference(SCENARIOS[index].reference);
  };

  const start = async () => {
    setMessage(null);
    setBusy(true);
    chunks.current = [];
    const nextRecorder = new BrowserVadRecorder();
    recorder.current = nextRecorder;
    try {
      metadata.current = await nextRecorder.start(
        (pcm) => chunks.current.push(pcm.slice(0)),
        () => undefined,
        profile,
        inputDeviceId,
      );
      setRecording(true);
    } catch (error) {
      nextRecorder.stop();
      setMessage({
        text: error instanceof Error ? error.message : "Не удалось начать запись.",
        tone: "error",
      });
    } finally {
      setBusy(false);
    }
  };

  const stop = async () => {
    setBusy(true);
    recorder.current?.stop();
    recorder.current = null;
    setRecording(false);
    const captureMetadata = metadata.current;
    if (!captureMetadata || chunks.current.length === 0) {
      setMessage({ text: "Запись пуста. Попробуйте записать сценарий ещё раз.", tone: "error" });
      setBusy(false);
      return;
    }
    try {
      const capture: SavedCapture = {
        id: `${Date.now()}-${scenario.id}`,
        scenarioId: scenario.id,
        reference: reference.trim(),
        tags: scenario.tags,
        profile,
        noiseOnly: Boolean(scenario.noiseOnly),
        sessionSequence: captures.length + 1,
        createdAt: new Date().toISOString(),
        metadata: captureMetadata,
        audio: encodeWav(chunks.current, captureMetadata.sampleRate),
      };
      await saveCapture(capture);
      const next = await listCaptures();
      setCaptures(next);
      setMessage({ text: "Запись сохранена локально на этом устройстве.", tone: "success" });
      if (scenarioIndex < SCENARIOS.length - 1) selectScenario(scenarioIndex + 1);
    } catch (error) {
      setMessage({
        text: error instanceof Error ? error.message : "Не удалось сохранить запись локально.",
        tone: "error",
      });
    } finally {
      setBusy(false);
    }
  };

  const exportManifest = () => {
    const manifest = captures.map((capture) => ({
      audio: `${capture.id}.wav`,
      reference: capture.reference,
      tags: capture.tags,
      profile: capture.profile,
      noise_only: capture.noiseOnly,
      session_sequence: capture.sessionSequence,
      capture: capture.metadata,
    }));
    download(
      new Blob([JSON.stringify(manifest, null, 2)], { type: "application/json" }),
      "stt-manifest.json",
    );
  };

  return (
    <section
      className="stt-capture"
      id="stt-guided-capture"
      aria-labelledby="stt-capture-title"
      aria-busy={busy}
    >
      <header className="stt-capture-header">
        <div>
          <h3 id="stt-capture-title">Приватный корпус речи</h3>
          <p><IconInterfaceSecurityShield4 size={16} aria-hidden="true" /> Записи остаются только на этом устройстве.</p>
        </div>
        <strong className="stt-capture-count" aria-label={`Сохранено сценариев: ${completedCount} из ${SCENARIOS.length}`}>
          {completedCount}<span>/{SCENARIOS.length}</span>
        </strong>
      </header>

      <div
        className="stt-capture-progress"
        role="progressbar"
        aria-label="Прогресс сбора тестовых записей"
        aria-valuemin={0}
        aria-valuemax={SCENARIOS.length}
        aria-valuenow={completedCount}
      >
        <span style={{ transform: `scaleX(${progress / 100})` }} />
      </div>

      <div className="stt-capture-editor">
        <label>
          Сценарий {scenarioIndex + 1} из {SCENARIOS.length}
          <CustomSelect value={scenarioIndex} onChange={(event) => selectScenario(Number(event.target.value))} disabled={recording || busy}>
            {SCENARIOS.map((item, index) => (
              <option key={item.id} value={index}>
                {index + 1}. {item.title}{completedScenarioIds.has(item.id) ? " — записано" : ""}
              </option>
            ))}
          </CustomSelect>
        </label>
        <label>
          Эталонный текст
          <textarea rows={3} value={reference} onChange={(event) => setReference(event.target.value)} disabled={recording || busy} />
          <small>{scenario.noiseOnly ? "Шумовой сценарий: оставьте поле пустым." : "Исправьте текст перед сохранением, если произнесли иначе."}</small>
        </label>
      </div>

      <div className="stt-capture-actions">
        {busy
          ? (
            <button className="primary-button" type="button" disabled>
              <IconInterfaceSpirals className="stt-capture-spinner is-spinning" size={20} aria-hidden="true" />
              {recording ? "Сохраняю…" : "Подключаю микрофон…"}
            </button>
          )
          : !recording
          ? (
            <button className="primary-button" type="button" onClick={() => void start()}>
              <FigmaMicIcon width={20} height={20} aria-hidden="true" /> Начать запись
            </button>
          )
          : (
            <button className="danger-button" type="button" onClick={() => void stop()}>
              <IconInterfaceTimeStopWatchCircle size={16} aria-hidden="true" /> Остановить и сохранить
            </button>
          )}
        <button className="secondary" type="button" onClick={exportManifest} disabled={!captures.length}>
          <IconInterfaceDownloadBox1 size={20} aria-hidden="true" /> Скачать manifest
        </button>
      </div>

      {message && (
        <div
          className={`notice stt-capture-notice is-${message.tone}`}
          role={message.tone === "error" ? "alert" : "status"}
          aria-live="polite"
        >
          {message.text}
        </div>
      )}

      <div className="stt-capture-saved">
        <div className="stt-capture-saved-heading">
          <h4>Сохранённые записи</h4>
          <span>{captures.length} WAV</span>
        </div>
        {captures.length === 0 ? (
          <p className="stt-capture-empty">Здесь появятся записи, которые можно скачать по одной.</p>
        ) : (
          <ul className="stt-capture-files">
            {captures.map((capture) => {
              const savedScenario = SCENARIOS.find((item) => item.id === capture.scenarioId);
              const title = savedScenario?.title ?? capture.scenarioId;
              return (
                <li key={capture.id}>
                  <button
                    type="button"
                    onClick={() => download(capture.audio, `${capture.id}.wav`)}
                    aria-label={`Скачать WAV: ${title}`}
                  >
                    <IconInterfaceFavoriteLike1 size={16} aria-hidden="true" />
                    <span>{title}</span>
                    <IconInterfaceDownloadBox1 size={16} aria-hidden="true" />
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );
}
