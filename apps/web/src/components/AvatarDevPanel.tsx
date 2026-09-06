import React, { useState, useEffect, useCallback } from "react";
import {
  Sparkles,
  Smile,
  Hand,
  Volume2,
  Square,
  RotateCcw,
  Sliders,
  X,
  SendHorizontal,
  Check,
  Activity,
  Maximize2,
  Minimize2,
  RefreshCw,
} from "lucide-react";
import {
  sendAvatarTestEmotion,
  sendAvatarTestGesture,
  sendAvatarTestPhrase,
  stopAvatar,
  getAvatarStatus,
} from "../api";
import { closeQaStudioWindow, isDesktopApp } from "../desktop";
import { getCurrentWindow } from "@tauri-apps/api/window";
import type { AvatarStatusResponse } from "../types";

export interface AvatarDevPanelProps {
  isOpen: boolean;
  onClose: () => void;
  avatarStatus?: AvatarStatusResponse | null;
}

interface EmotionItem {
  id: string;
  name: string;
  category: "morphs" | "positive" | "cognitive" | "complex";
  emoji: string;
  hint: string;
}

interface GestureItem {
  id: string;
  name: string;
  category: "hands" | "body" | "speech";
  hint: string;
}

interface TestPreset {
  title: string;
  description: string;
  text: string;
  emotion: string;
  gesture: string;
}

const EMOTIONS_CATALOG: EmotionItem[] = [
  // Facial Morphs & Novel
  { id: "pouting", name: "Надутые щёчки", category: "morphs", emoji: "🥺", hint: "CheekPuff + MouthPucker" },
  { id: "teasing", name: "Показать язык", category: "morphs", emoji: "😜", hint: "TongueOut + Squint" },
  { id: "wink", name: "Подмигнуть (правый)", category: "morphs", emoji: "😉", hint: "BlinkRight + SquintLeft" },
  { id: "wink_left", name: "Подмигнуть (левый)", category: "morphs", emoji: "👁️", hint: "BlinkLeft + SquintRight" },
  { id: "smirk", name: "Ухмылка", category: "morphs", emoji: "😏", hint: "MouthSmileRight + BrowOuterUp" },
  { id: "playful", name: "Игривая / Озорная", category: "morphs", emoji: "😋", hint: "TongueOut (мягкий) + Squint" },

  // Positive
  { id: "happy", name: "Радость", category: "positive", emoji: "😊", hint: "Базовая радость" },
  { id: "excited", name: "Восторг", category: "positive", emoji: "🤩", hint: "EyeWide + Smile" },
  { id: "proud", name: "Гордость / Довольная", category: "positive", emoji: "😌", hint: "BrowOuterUp + Squint" },
  { id: "touched", name: "Растроганная", category: "positive", emoji: "🥰", hint: "BrowInnerUp + Squint" },
  { id: "relaxed", name: "Расслабленность", category: "positive", emoji: "☕", hint: "Мягкий релакс" },

  // Cognitive & Attention
  { id: "thinking", name: "Задумчивость", category: "cognitive", emoji: "🤔", hint: "Фокус и размышление" },
  { id: "curious", name: "Любопытство", category: "cognitive", emoji: "🧐", hint: "EyeWide + BrowOuterUp" },
  { id: "surprised", name: "Удивление", category: "cognitive", emoji: "😮", hint: "Surprised + EyeWide" },
  { id: "shocked", name: "Шок / Ошеломление", category: "cognitive", emoji: "😱", hint: "Surprised + JawOpen" },
  { id: "skeptical", name: "Скептицизм", category: "cognitive", emoji: "🤨", hint: "BrowOuterUpRight + BrowDownLeft" },
  { id: "confused", name: "Озадаченность", category: "cognitive", emoji: "😕", hint: "Brow asymmetry + MouthFrown" },

  // Complex & Negative
  { id: "embarrassed", name: "Смущение", category: "complex", emoji: "😳", hint: "EyeSquint + BrowInnerUp" },
  { id: "concerned", name: "Беспокойство", category: "complex", emoji: "😟", hint: "BrowInnerUp + MouthFrown" },
  { id: "sad", name: "Грусть", category: "complex", emoji: "😢", hint: "Базовая грусть" },
  { id: "angry", name: "Злость", category: "complex", emoji: "😠", hint: "Базовая злость" },
  { id: "annoyed", name: "Раздражение", category: "complex", emoji: "😤", hint: "Умеренная злость" },
  { id: "sleepy", name: "Сонливость", category: "complex", emoji: "🥱", hint: "EyeSquint + MouthClose" },
  { id: "neutral", name: "Нейтральная", category: "complex", emoji: "😐", hint: "Базовое состояние покоя" },
];

const GESTURES_CATALOG: GestureItem[] = [
  // Hands & Greetings
  { id: "greeting_right", name: "Поднять правую руку", category: "hands", hint: "Приветствие правой рукой" },
  { id: "greeting_left", name: "Поднять левую руку", category: "hands", hint: "Приветствие левой рукой" },
  { id: "greeting", name: "Приветствие (авто)", category: "hands", hint: "Синхронное приветствие" },
  { id: "farewell_right", name: "Помахать правой рукой", category: "hands", hint: "Прощание правой" },
  { id: "farewell_left", name: "Помахать левой рукой", category: "hands", hint: "Прощание левой" },
  { id: "farewell", name: "Прощание (авто)", category: "hands", hint: "Мягкое прощание" },
  { id: "greeting_casual", name: "Непринуждённый жест", category: "hands", hint: "Лёгкое касание / привет" },

  // Body & Reactions
  { id: "nod", name: "Кивок головой", category: "body", hint: "Подтверждение / согласие" },
  { id: "disagreement", name: "Покачивание головой", category: "body", hint: "Несогласие / отрицание" },
  { id: "shrug", name: "Пожать плечами", category: "body", hint: "Недоумение / пожимание" },
  { id: "surprise", name: "Всплеск / Удивление", category: "body", hint: "Реакция на неожиданность" },
  { id: "frustration", name: "Фрустрация", category: "body", hint: "Досада / разочарование" },
  { id: "thinking_right", name: "Задуматься (справа)", category: "body", hint: "Поза мыслителя" },
  { id: "thinking_left", name: "Задуматься (слева)", category: "body", hint: "Поза мыслителя (зеркально)" },

  // Speech & Explanation
  { id: "talk_right", name: "Речь правой рукой", category: "speech", hint: "Жестикуляция правой" },
  { id: "talk_left", name: "Речь левой рукой", category: "speech", hint: "Жестикуляция левой" },
  { id: "explanation_right", name: "Объяснение (справа)", category: "speech", hint: "Разъясняющий жест" },
  { id: "explanation_left", name: "Объяснение (слева)", category: "speech", hint: "Разъясняющий жест (зеркало)" },
  { id: "question_right", name: "Вопрос (справа)", category: "speech", hint: "Вопросительный жест" },
  { id: "question_left", name: "Вопрос (слева)", category: "speech", hint: "Вопросительный жест (зеркало)" },
];

const PRESETS: TestPreset[] = [
  {
    title: "Тест обеих рук (поочередно)",
    description: "Проверяет поднятие сначала правой, а затем левой руки без застревания.",
    text: "Ну смотри, давай проверим руки! [[avatar gesture=greeting_right]] Вот я поднимаю правую руку. [[avatar gesture=greeting_left]] А теперь поднимаю левую руку!",
    emotion: "happy",
    gesture: "greeting_right",
  },
  {
    title: "Тест мимики (винки, язык, щёчки)",
    description: "Проверяет быструю смену морфов: правый глаз, левый глаз, язык и надутые щёчки.",
    text: "Вот подмигиваю тебе правым глазом. [[avatar emotion=wink_left gesture=none]] А теперь левым. [[avatar emotion=teasing gesture=none]] Могу язык показать! [[avatar emotion=pouting gesture=none]] А теперь надула щёчки!",
    emotion: "wink",
    gesture: "none",
  },
  {
    title: "Каскад всего арсенала (мульти-сегмент)",
    description: "Комплексный стресс-тест всех сегментов диалога и жестов подряд.",
    text: "Ну смотри, покажу весь арсенал! [[avatar emotion=surprised gesture=surprise]] Удивилась, [[avatar emotion=thinking gesture=thinking_right]] теперь задумалась, [[avatar emotion=smirk gesture=shrug]] пожимаю плечами [[avatar emotion=happy gesture=greeting_casual]] и улыбаюсь тебе!",
    emotion: "excited",
    gesture: "greeting_casual",
  },
  {
    title: "Согласие и кивок",
    description: "Проверяет естественный кивок головы и одобрение без лишних движений руками.",
    text: "Да, абсолютно с тобой согласна! [[avatar emotion=proud gesture=nod]] Именно так всё и устроено.",
    emotion: "proud",
    gesture: "nod",
  },
  {
    title: "Сомнение и несогласие",
    description: "Проверяет покачивание головой и скептическое выражение лица.",
    text: "Хм, я очень сильно в этом сомневаюсь. [[avatar emotion=skeptical gesture=disagreement]] Нет, так точно не пойдёт!",
    emotion: "skeptical",
    gesture: "disagreement",
  },
  {
    title: "Эмоциональный спектр (злость, удивление, растерянность)",
    description: "Проверяет выразительные движения: фрустрацию, всплеск удивления и озадаченный шраг.",
    text: "[[avatar emotion=angry gesture=frustration]] Ну сколько можно! [[avatar emotion=surprised gesture=surprise]] Ого, ты правда это сделал? [[avatar emotion=confused gesture=shrug]] Я просто поражена!",
    emotion: "angry",
    gesture: "frustration",
  },
];

export function AvatarDevPanel({ isOpen, onClose, avatarStatus }: AvatarDevPanelProps) {
  const [activeTab, setActiveTab] = useState<"emotions" | "gestures" | "speech">("emotions");
  const [emotionCategory, setEmotionCategory] = useState<string>("all");
  const [gestureCategory, setGestureCategory] = useState<string>("all");
  const [intensity, setIntensity] = useState<number>(1.0);
  const [gestureInterrupt, setGestureInterrupt] = useState<boolean>(true);
  const [lastAction, setLastAction] = useState<string | null>(null);
  const [isExecuting, setIsExecuting] = useState<boolean>(false);
  const [activeEmotionId, setActiveEmotionId] = useState<string | null>(null);
  const [activeGestureId, setActiveGestureId] = useState<string | null>(null);
  const [customPhrase, setCustomPhrase] = useState<string>(
    "Привет! Я тестирую работу аватара и всех его движений.",
  );
  const [phraseEmotion, setPhraseEmotion] = useState<string>("neutral");
  const [phraseGesture, setPhraseGesture] = useState<string>("greeting_right");
  const [isMinimized, setIsMinimized] = useState<boolean>(false);

  const isConnected = (avatarStatus?.client_count ?? 0) > 0;
  const clientName = avatarStatus?.clients?.[0]?.client_name ?? "Unity Avatar";
  const presenceState = avatarStatus?.clients?.[0]?.state ?? "idle";

  const showNotification = useCallback((message: string) => {
    setLastAction(message);
    const timer = setTimeout(() => {
      setLastAction((prev) => (prev === message ? null : prev));
    }, 3500);
    return () => clearTimeout(timer);
  }, []);

  const handleTriggerEmotion = async (emotionId: string) => {
    setIsExecuting(true);
    setActiveEmotionId(emotionId);
    try {
      await sendAvatarTestEmotion({ emotion: emotionId, intensity });
      const found = EMOTIONS_CATALOG.find((e) => e.id === emotionId);
      showNotification(`Эмоция «${found?.name ?? emotionId}» отправлена (${Math.round(intensity * 100)}%)`);
    } catch (err) {
      showNotification(`Ошибка отправки эмоции: ${String(err)}`);
    } finally {
      setIsExecuting(false);
    }
  };

  const handleTriggerGesture = async (gestureId: string) => {
    setIsExecuting(true);
    setActiveGestureId(gestureId);
    try {
      await sendAvatarTestGesture({
        gesture: gestureId,
        intensity,
        interrupt: gestureInterrupt,
      });
      const found = GESTURES_CATALOG.find((g) => g.id === gestureId);
      showNotification(`Жест «${found?.name ?? gestureId}» запущен`);
    } catch (err) {
      showNotification(`Ошибка отправки жеста: ${String(err)}`);
    } finally {
      setIsExecuting(false);
    }
  };

  const handleSpeak = async (text: string, emo: string, gest: string) => {
    if (!text.trim()) return;
    setIsExecuting(true);
    try {
      await sendAvatarTestPhrase({
        text,
        emotion: emo,
        gesture: gest,
        gesture_intensity: intensity,
        interrupt: true,
      });
      showNotification("Фраза поставлена в очередь речи аватара");
    } catch (err) {
      showNotification(`Ошибка воспроизведения фразы: ${String(err)}`);
    } finally {
      setIsExecuting(false);
    }
  };

  const handleReset = async () => {
    setIsExecuting(true);
    try {
      await stopAvatar();
      await sendAvatarTestEmotion({ emotion: "neutral", intensity: 1.0 });
      setActiveEmotionId("neutral");
      setActiveGestureId(null);
      showNotification("Аватар сброшен в нейтральное состояние");
    } catch (err) {
      showNotification(`Ошибка сброса: ${String(err)}`);
    } finally {
      setIsExecuting(false);
    }
  };

  if (!isOpen) return null;

  const filteredEmotions =
    emotionCategory === "all"
      ? EMOTIONS_CATALOG
      : EMOTIONS_CATALOG.filter((e) => e.category === emotionCategory);

  const filteredGestures =
    gestureCategory === "all"
      ? GESTURES_CATALOG
      : GESTURES_CATALOG.filter((g) => g.category === gestureCategory);

  return (
    <div
      className={`avatar-dev-studio-window ${isMinimized ? "is-minimized" : ""}`}
      role="dialog"
      aria-label="Лаборатория тестирования аватара"
    >
      {/* Window Header */}
      <div className="avatar-dev-header">
        <div className="avatar-dev-title-row">
          <div className="avatar-dev-badge">
            <Sparkles size={13} className="avatar-dev-sparkle-icon" />
            <span>QA Studio</span>
          </div>
          <h3 className="avatar-dev-title">Лаборатория аватара</h3>
          <div className={`avatar-dev-connection-tag ${isConnected ? "is-online" : "is-offline"}`}>
            <span className="connection-dot" />
            <span>{isConnected ? `${clientName} (${presenceState})` : "Unity оффлайн"}</span>
          </div>
        </div>

        <div className="avatar-dev-header-actions">
          <button
            type="button"
            className="avatar-dev-btn-danger"
            onClick={handleReset}
            title="Немедленно остановить речь и вернуть в нейтраль"
            disabled={isExecuting}
          >
            <Square size={12} />
            <span>Сброс / Стоп</span>
          </button>
          <button
            type="button"
            className="avatar-dev-icon-btn"
            onClick={() => setIsMinimized((v) => !v)}
            title={isMinimized ? "Развернуть" : "Свернуть"}
          >
            {isMinimized ? <Maximize2 size={13} /> : <Minimize2 size={13} />}
          </button>
          <button
            type="button"
            className="avatar-dev-icon-btn"
            onClick={onClose}
            title="Закрыть панель тестировщика"
          >
            <X size={14} />
          </button>
        </div>
      </div>

      {!isMinimized && (
        <>
          {/* Global Intensity & Controls Bar */}
          <div className="avatar-dev-toolbar">
            <div className="avatar-dev-slider-group">
              <Sliders size={13} className="avatar-dev-toolbar-icon" />
              <span className="avatar-dev-slider-label">Сила:</span>
              <input
                type="range"
                min="0.1"
                max="1.0"
                step="0.05"
                value={intensity}
                onChange={(e) => setIntensity(parseFloat(e.target.value))}
                className="avatar-dev-range"
              />
              <span className="avatar-dev-slider-value">{Math.round(intensity * 100)}%</span>
            </div>

            <div className="avatar-dev-tabs">
              <button
                type="button"
                className={`avatar-dev-tab ${activeTab === "emotions" ? "is-active" : ""}`}
                onClick={() => setActiveTab("emotions")}
              >
                <Smile size={13} />
                <span>Эмоции ({EMOTIONS_CATALOG.length})</span>
              </button>
              <button
                type="button"
                className={`avatar-dev-tab ${activeTab === "gestures" ? "is-active" : ""}`}
                onClick={() => setActiveTab("gestures")}
              >
                <Hand size={13} />
                <span>Жесты ({GESTURES_CATALOG.length})</span>
              </button>
              <button
                type="button"
                className={`avatar-dev-tab ${activeTab === "speech" ? "is-active" : ""}`}
                onClick={() => setActiveTab("speech")}
              >
                <Volume2 size={13} />
                <span>Речь & Сценарии</span>
              </button>
            </div>
          </div>

          {/* Tab 1: Emotions (24 Emotions) */}
          {activeTab === "emotions" && (
            <div className="avatar-dev-content-pane">
              <div className="avatar-dev-subnav">
                {[
                  { id: "all", label: "Все (24)" },
                  { id: "morphs", label: "Мимика & Особые" },
                  { id: "positive", label: "Позитивные" },
                  { id: "cognitive", label: "Мыслительные" },
                  { id: "complex", label: "Негатив & Покой" },
                ].map((cat) => (
                  <button
                    key={cat.id}
                    type="button"
                    className={`avatar-dev-filter-chip ${emotionCategory === cat.id ? "is-active" : ""}`}
                    onClick={() => setEmotionCategory(cat.id)}
                  >
                    {cat.label}
                  </button>
                ))}
              </div>

              <div className="avatar-dev-grid avatar-dev-emotions-grid">
                {filteredEmotions.map((item) => {
                  const isCurrent = activeEmotionId === item.id;
                  return (
                    <button
                      key={item.id}
                      type="button"
                      className={`avatar-dev-card ${isCurrent ? "is-active-trigger" : ""}`}
                      onClick={() => void handleTriggerEmotion(item.id)}
                      disabled={isExecuting}
                      title={`Запустить эмоцию: ${item.name} (${item.hint})`}
                    >
                      <span className="avatar-dev-card-emoji">{item.emoji}</span>
                      <div className="avatar-dev-card-info">
                        <span className="avatar-dev-card-name">{item.name}</span>
                        <span className="avatar-dev-card-code">{item.id}</span>
                      </div>
                      {isCurrent && <Check size={12} className="avatar-dev-active-check" />}
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* Tab 2: Gestures */}
          {activeTab === "gestures" && (
            <div className="avatar-dev-content-pane">
              <div className="avatar-dev-subnav-row">
                <div className="avatar-dev-subnav">
                  {[
                    { id: "all", label: "Все жесты" },
                    { id: "hands", label: "Руки & Приветствия" },
                    { id: "body", label: "Тело & Реакции" },
                    { id: "speech", label: "Речевые жесты" },
                  ].map((cat) => (
                    <button
                      key={cat.id}
                      type="button"
                      className={`avatar-dev-filter-chip ${gestureCategory === cat.id ? "is-active" : ""}`}
                      onClick={() => setGestureCategory(cat.id)}
                    >
                      {cat.label}
                    </button>
                  ))}
                </div>

                <label className="avatar-dev-checkbox-label">
                  <input
                    type="checkbox"
                    checked={gestureInterrupt}
                    onChange={(e) => setGestureInterrupt(e.target.checked)}
                  />
                  <span>Прерывать текущую анимацию</span>
                </label>
              </div>

              <div className="avatar-dev-grid avatar-dev-gestures-grid">
                {filteredGestures.map((item) => {
                  const isCurrent = activeGestureId === item.id;
                  return (
                    <button
                      key={item.id}
                      type="button"
                      className={`avatar-dev-card avatar-dev-gesture-card ${isCurrent ? "is-active-trigger" : ""}`}
                      onClick={() => void handleTriggerGesture(item.id)}
                      disabled={isExecuting}
                      title={`Выполнить жест: ${item.name} (${item.hint})`}
                    >
                      <Hand size={15} className="avatar-dev-gesture-icon" />
                      <div className="avatar-dev-card-info">
                        <span className="avatar-dev-card-name">{item.name}</span>
                        <span className="avatar-dev-card-code">{item.id}</span>
                      </div>
                      {isCurrent && <Activity size={12} className="avatar-dev-active-check" />}
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* Tab 3: Speech & Presets */}
          {activeTab === "speech" && (
            <div className="avatar-dev-content-pane">
              <div className="avatar-dev-presets-section">
                <h4 className="avatar-dev-section-title">Быстрые сценарии тестирования</h4>
                <div className="avatar-dev-presets-grid">
                  {PRESETS.map((preset, idx) => (
                    <div key={idx} className="avatar-dev-preset-card">
                      <div className="avatar-dev-preset-top">
                        <span className="avatar-dev-preset-title">{preset.title}</span>
                        <button
                          type="button"
                          className="avatar-dev-btn-preset-run"
                          onClick={() => void handleSpeak(preset.text, preset.emotion, preset.gesture)}
                          disabled={isExecuting}
                        >
                          <SendHorizontal size={12} />
                          <span>Запустить</span>
                        </button>
                      </div>
                      <p className="avatar-dev-preset-desc">{preset.description}</p>
                      <code className="avatar-dev-preset-quote">«{preset.text}»</code>
                    </div>
                  ))}
                </div>
              </div>

              <div className="avatar-dev-custom-speech-section">
                <h4 className="avatar-dev-section-title">Произвольная тестовая фраза</h4>
                <div className="avatar-dev-speech-form">
                  <textarea
                    className="avatar-dev-textarea"
                    rows={3}
                    value={customPhrase}
                    onChange={(e) => setCustomPhrase(e.target.value)}
                    placeholder="Введите текст для озвучки аватаром..."
                  />
                  <div className="avatar-dev-speech-controls">
                    <div className="avatar-dev-select-pair">
                      <label>
                        <span>Начальная эмоция:</span>
                        <select
                          className="avatar-dev-select"
                          value={phraseEmotion}
                          onChange={(e) => setPhraseEmotion(e.target.value)}
                        >
                          {EMOTIONS_CATALOG.map((e) => (
                            <option key={e.id} value={e.id}>
                              {e.emoji} {e.name}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label>
                        <span>Начальный жест:</span>
                        <select
                          className="avatar-dev-select"
                          value={phraseGesture}
                          onChange={(e) => setPhraseGesture(e.target.value)}
                        >
                          <option value="auto">Авто (по смыслу)</option>
                          {GESTURES_CATALOG.map((g) => (
                            <option key={g.id} value={g.id}>
                              {g.name}
                            </option>
                          ))}
                        </select>
                      </label>
                    </div>
                    <button
                      type="button"
                      className="avatar-dev-btn-primary"
                      onClick={() => void handleSpeak(customPhrase, phraseEmotion, phraseGesture)}
                      disabled={isExecuting || !customPhrase.trim()}
                    >
                      <Volume2 size={14} />
                      <span>Произнести фразу</span>
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Footer Notice */}
          {lastAction && (
            <div className="avatar-dev-statusbar">
              <span className="avatar-dev-status-text">{lastAction}</span>
            </div>
          )}
        </>
      )}
    </div>
  );
}

export function AvatarDevStudioStandalonePage() {
  const [activeTab, setActiveTab] = useState<"emotions" | "gestures" | "speech">("emotions");
  const [emotionCategory, setEmotionCategory] = useState<string>("all");
  const [gestureCategory, setGestureCategory] = useState<string>("all");
  const [intensity, setIntensity] = useState<number>(1.0);
  const [gestureInterrupt, setGestureInterrupt] = useState<boolean>(true);
  const [lastAction, setLastAction] = useState<string | null>(null);
  const [isExecuting, setIsExecuting] = useState<boolean>(false);
  const [activeEmotionId, setActiveEmotionId] = useState<string | null>(null);
  const [activeGestureId, setActiveGestureId] = useState<string | null>(null);
  const [customPhrase, setCustomPhrase] = useState<string>(
    "Привет! Я тестирую работу аватара и всех его движений.",
  );
  const [phraseEmotion, setPhraseEmotion] = useState<string>("neutral");
  const [phraseGesture, setPhraseGesture] = useState<string>("greeting_right");
  const [avatarStatus, setAvatarStatus] = useState<AvatarStatusResponse | null>(null);
  const [isRefreshingStatus, setIsRefreshingStatus] = useState<boolean>(false);

  const isConnected = (avatarStatus?.client_count ?? 0) > 0;
  const clientName = avatarStatus?.clients?.[0]?.client_name ?? "Unity Avatar";
  const presenceState = avatarStatus?.clients?.[0]?.state ?? "idle";

  const showNotification = useCallback((message: string) => {
    setLastAction(message);
    const timer = window.setTimeout(() => {
      setLastAction((prev) => (prev === message ? null : prev));
    }, 4000);
    return () => window.clearTimeout(timer);
  }, []);

  const fetchAvatarStatus = useCallback(async () => {
    try {
      setIsRefreshingStatus(true);
      const st = await getAvatarStatus();
      setAvatarStatus(st);
    } catch {
      setAvatarStatus(null);
    } finally {
      setIsRefreshingStatus(false);
    }
  }, []);

  useEffect(() => {
    void fetchAvatarStatus();
    const interval = window.setInterval(() => {
      void fetchAvatarStatus();
    }, 2000);

    let channel: BroadcastChannel | null = null;
    try {
      channel = new BroadcastChannel("iris_qa_studio");
      channel.postMessage({ action: "state", open: true });
      channel.onmessage = (event: MessageEvent) => {
        if (event.data?.action === "close") {
          void handleCloseWindow();
        }
      };
    } catch {
      // Ignore
    }

    const handleBeforeUnload = () => {
      try {
        const ch = new BroadcastChannel("iris_qa_studio");
        ch.postMessage({ action: "closed" });
        ch.close();
      } catch {
        // Ignore
      }
    };

    window.addEventListener("beforeunload", handleBeforeUnload);

    return () => {
      window.clearInterval(interval);
      window.removeEventListener("beforeunload", handleBeforeUnload);
      try {
        channel?.close();
      } catch {
        // Ignore
      }
    };
  }, [fetchAvatarStatus]);

  const handleCloseWindow = async () => {
    try {
      const channel = new BroadcastChannel("iris_qa_studio");
      channel.postMessage({ action: "closed" });
      channel.close();
    } catch {
      // Ignore
    }
    await closeQaStudioWindow();
    if (isDesktopApp()) {
      try {
        await getCurrentWindow().close();
        return;
      } catch {
        // Fall back to window.close
      }
    }
    window.close();
  };

  const handleTriggerEmotion = async (emotionId: string) => {
    setIsExecuting(true);
    setActiveEmotionId(emotionId);
    try {
      await sendAvatarTestEmotion({ emotion: emotionId, intensity });
      const found = EMOTIONS_CATALOG.find((e) => e.id === emotionId);
      showNotification(`Эмоция «${found?.name ?? emotionId}» отправлена (${Math.round(intensity * 100)}%)`);
    } catch (err) {
      showNotification(`Ошибка отправки эмоции: ${String(err)}`);
    } finally {
      setIsExecuting(false);
    }
  };

  const handleTriggerGesture = async (gestureId: string) => {
    setIsExecuting(true);
    setActiveGestureId(gestureId);
    try {
      await sendAvatarTestGesture({
        gesture: gestureId,
        intensity,
        interrupt: gestureInterrupt,
      });
      const found = GESTURES_CATALOG.find((g) => g.id === gestureId);
      showNotification(`Жест «${found?.name ?? gestureId}» запущен`);
    } catch (err) {
      showNotification(`Ошибка отправки жеста: ${String(err)}`);
    } finally {
      setIsExecuting(false);
    }
  };

  const handleSpeak = async (text: string, emo: string, gest: string) => {
    if (!text.trim()) return;
    setIsExecuting(true);
    try {
      await sendAvatarTestPhrase({
        text,
        emotion: emo,
        gesture: gest,
        gesture_intensity: intensity,
        interrupt: true,
      });
      showNotification("Фраза поставлена в очередь речи аватара");
    } catch (err) {
      showNotification(`Ошибка воспроизведения фразы: ${String(err)}`);
    } finally {
      setIsExecuting(false);
    }
  };

  const handleReset = async () => {
    setIsExecuting(true);
    try {
      await stopAvatar();
      await sendAvatarTestEmotion({ emotion: "neutral", intensity: 1.0 });
      setActiveEmotionId("neutral");
      setActiveGestureId(null);
      showNotification("Аватар сброшен в нейтральное состояние");
    } catch (err) {
      showNotification(`Ошибка сброса: ${String(err)}`);
    } finally {
      setIsExecuting(false);
    }
  };

  const handleStopSpeech = async () => {
    setIsExecuting(true);
    try {
      await stopAvatar();
      showNotification("Речь и движения аватара остановлены");
    } catch (err) {
      showNotification(`Ошибка остановки: ${String(err)}`);
    } finally {
      setIsExecuting(false);
    }
  };

  const filteredEmotions =
    emotionCategory === "all"
      ? EMOTIONS_CATALOG
      : EMOTIONS_CATALOG.filter((e) => e.category === emotionCategory);

  const filteredGestures =
    gestureCategory === "all"
      ? GESTURES_CATALOG
      : GESTURES_CATALOG.filter((g) => g.category === gestureCategory);

  return (
    <div className="avatar-dev-standalone-page" role="region" aria-label="Автономное окно тестирования аватара">
      {/* Standalone Window Header */}
      <div className="avatar-dev-header">
        <div className="avatar-dev-title-row">
          <div className="avatar-dev-badge">
            <Sparkles size={14} className="avatar-dev-sparkle-icon" />
            <span>QA STUDIO v2.0</span>
          </div>
          <div className="avatar-dev-titles-group">
            <h1 className="avatar-dev-title">Iris QA Studio</h1>
            <span className="avatar-dev-subtitle">Автономный стенд тестирования аватара</span>
          </div>
          <div className={`avatar-dev-connection-tag ${isConnected ? "is-online" : "is-offline"}`}>
            <span className="connection-dot" />
            <span>{isConnected ? `${clientName} • ${presenceState}` : "Unity оффлайн"}</span>
          </div>
        </div>

        <div className="avatar-dev-header-actions">
          <button
            type="button"
            className="avatar-dev-btn-action"
            onClick={() => void fetchAvatarStatus()}
            title="Обновить статус соединения"
            disabled={isRefreshingStatus}
          >
            <RefreshCw size={12} className={isRefreshingStatus ? "spin" : ""} />
            <span>Обновить</span>
          </button>
          <button
            type="button"
            className="avatar-dev-btn-action"
            onClick={() => void handleStopSpeech()}
            title="Остановить текущую речь аватара"
            disabled={isExecuting}
          >
            <Square size={12} />
            <span>Стоп</span>
          </button>
          <button
            type="button"
            className="avatar-dev-btn-danger"
            onClick={() => void handleReset()}
            title="Немедленно остановить всё и сбросить в нейтраль"
            disabled={isExecuting}
          >
            <RotateCcw size={12} />
            <span>Сброс</span>
          </button>
          <button
            type="button"
            className="avatar-dev-btn-close"
            onClick={() => void handleCloseWindow()}
            title="Закрыть отдельное окно тестирования"
          >
            <X size={14} />
            <span>Закрыть окно</span>
          </button>
        </div>
      </div>

      {/* Global Intensity & Controls Bar */}
      <div className="avatar-dev-toolbar">
        <div className="avatar-dev-controls-left">
          <div className="avatar-dev-slider-group">
            <Sliders size={13} className="avatar-dev-toolbar-icon" />
            <span className="avatar-dev-slider-label">Сила:</span>
            <input
              type="range"
              min="0.1"
              max="1.0"
              step="0.05"
              value={intensity}
              onChange={(e) => setIntensity(parseFloat(e.target.value))}
              className="avatar-dev-range"
            />
            <span className="avatar-dev-slider-value">{Math.round(intensity * 100)}%</span>
          </div>

          <label className="avatar-dev-checkbox-label">
            <input
              type="checkbox"
              checked={gestureInterrupt}
              onChange={(e) => setGestureInterrupt(e.target.checked)}
            />
            <span>Прерывать текущие жесты</span>
          </label>
        </div>

        <div className="avatar-dev-tabs">
          <button
            type="button"
            className={`avatar-dev-tab ${activeTab === "emotions" ? "is-active" : ""}`}
            onClick={() => setActiveTab("emotions")}
          >
            <Smile size={13} />
            <span>Эмоции ({EMOTIONS_CATALOG.length})</span>
          </button>
          <button
            type="button"
            className={`avatar-dev-tab ${activeTab === "gestures" ? "is-active" : ""}`}
            onClick={() => setActiveTab("gestures")}
          >
            <Hand size={13} />
            <span>Жесты ({GESTURES_CATALOG.length})</span>
          </button>
          <button
            type="button"
            className={`avatar-dev-tab ${activeTab === "speech" ? "is-active" : ""}`}
            onClick={() => setActiveTab("speech")}
          >
            <Volume2 size={13} />
            <span>Речь & Сценарии</span>
          </button>
        </div>
      </div>

      {/* Tab 1: Emotions (24 Emotions) */}
      {activeTab === "emotions" && (
        <div className="avatar-dev-content-pane">
          <div className="avatar-dev-subnav">
            {[
              { id: "all", label: "Все (24)" },
              { id: "morphs", label: "Мимика & Особые" },
              { id: "positive", label: "Позитивные" },
              { id: "cognitive", label: "Мыслительные" },
              { id: "complex", label: "Негатив & Покой" },
            ].map((cat) => (
              <button
                key={cat.id}
                type="button"
                className={`avatar-dev-subnav-btn ${emotionCategory === cat.id ? "is-active" : ""}`}
                onClick={() => setEmotionCategory(cat.id)}
              >
                {cat.label}
              </button>
            ))}
          </div>

          <div className="avatar-dev-grid">
            {filteredEmotions.map((item) => {
              const isActive = activeEmotionId === item.id;
              return (
                <button
                  key={item.id}
                  type="button"
                  className={`avatar-dev-card ${isActive ? "is-active" : ""}`}
                  onClick={() => void handleTriggerEmotion(item.id)}
                  disabled={isExecuting}
                >
                  <div className="avatar-dev-card-top">
                    <span className="avatar-dev-card-emoji">{item.emoji}</span>
                    <span className="avatar-dev-card-id">{item.id}</span>
                  </div>
                  <strong className="avatar-dev-card-title">{item.name}</strong>
                  <span className="avatar-dev-card-hint">{item.hint}</span>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Tab 2: Gestures (20 Gestures) */}
      {activeTab === "gestures" && (
        <div className="avatar-dev-content-pane">
          <div className="avatar-dev-subnav">
            {[
              { id: "all", label: "Все (20)" },
              { id: "hands", label: "Руки & Приветствия" },
              { id: "body", label: "Корпус & Голова" },
              { id: "speech", label: "Речевые жесты" },
            ].map((cat) => (
              <button
                key={cat.id}
                type="button"
                className={`avatar-dev-subnav-btn ${gestureCategory === cat.id ? "is-active" : ""}`}
                onClick={() => setGestureCategory(cat.id)}
              >
                {cat.label}
              </button>
            ))}
          </div>

          <div className="avatar-dev-grid">
            {filteredGestures.map((item) => {
              const isActive = activeGestureId === item.id;
              return (
                <button
                  key={item.id}
                  type="button"
                  className={`avatar-dev-card ${isActive ? "is-active" : ""}`}
                  onClick={() => void handleTriggerGesture(item.id)}
                  disabled={isExecuting}
                >
                  <div className="avatar-dev-card-top">
                    <span className="avatar-dev-card-category-badge">{item.category}</span>
                    <span className="avatar-dev-card-id">{item.id}</span>
                  </div>
                  <strong className="avatar-dev-card-title">{item.name}</strong>
                  <span className="avatar-dev-card-hint">{item.hint}</span>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Tab 3: Speech & Presets */}
      {activeTab === "speech" && (
        <div className="avatar-dev-content-pane">
          <div className="avatar-dev-presets-section">
            <h4 className="avatar-dev-section-title">Быстрые сценарии тестирования</h4>
            <div className="avatar-dev-presets-grid">
              {PRESETS.map((preset, idx) => (
                <div key={idx} className="avatar-dev-preset-card">
                  <div className="avatar-dev-preset-top">
                    <span className="avatar-dev-preset-title">{preset.title}</span>
                    <button
                      type="button"
                      className="avatar-dev-btn-preset-run"
                      onClick={() => void handleSpeak(preset.text, preset.emotion, preset.gesture)}
                      disabled={isExecuting}
                    >
                      <SendHorizontal size={12} />
                      <span>Запустить</span>
                    </button>
                  </div>
                  <p className="avatar-dev-preset-desc">{preset.description}</p>
                  <code className="avatar-dev-preset-quote">«{preset.text}»</code>
                </div>
              ))}
            </div>
          </div>

          <div className="avatar-dev-custom-speech-section">
            <h4 className="avatar-dev-section-title">Произвольная тестовая фраза</h4>
            <div className="avatar-dev-speech-form">
              <textarea
                className="avatar-dev-textarea"
                rows={3}
                value={customPhrase}
                onChange={(e) => setCustomPhrase(e.target.value)}
                placeholder="Введите текст для озвучки аватаром..."
              />
              <div className="avatar-dev-speech-controls">
                <div className="avatar-dev-select-pair">
                  <label>
                    <span>Начальная эмоция:</span>
                    <select
                      className="avatar-dev-select"
                      value={phraseEmotion}
                      onChange={(e) => setPhraseEmotion(e.target.value)}
                    >
                      {EMOTIONS_CATALOG.map((e) => (
                        <option key={e.id} value={e.id}>
                          {e.emoji} {e.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <span>Начальный жест:</span>
                    <select
                      className="avatar-dev-select"
                      value={phraseGesture}
                      onChange={(e) => setPhraseGesture(e.target.value)}
                    >
                      <option value="auto">Авто (по смыслу)</option>
                      {GESTURES_CATALOG.map((g) => (
                        <option key={g.id} value={g.id}>
                          {g.name}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                <button
                  type="button"
                  className="avatar-dev-btn-primary"
                  onClick={() => void handleSpeak(customPhrase, phraseEmotion, phraseGesture)}
                  disabled={isExecuting || !customPhrase.trim()}
                >
                  <Volume2 size={14} />
                  <span>Произнести фразу</span>
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Footer Statusbar */}
      <div className="avatar-dev-statusbar">
        <span className="avatar-dev-status-text">
          {lastAction ? (
            <>
              <Check size={13} style={{ color: "#34d399", display: "inline-block", verticalAlign: "middle", marginRight: 4 }} />
              <span>{lastAction}</span>
            </>
          ) : (
            <span>Готов к тестированию аватара. Выберите эмоцию, жест или сценарий речи.</span>
          )}
        </span>
        <span className="avatar-dev-backend-tag">Backend: 127.0.0.1:8000</span>
      </div>
    </div>
  );
}

