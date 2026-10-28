import { Disclosure } from "../components/Disclosure";

import { MaterialButton } from "../components/MaterialButton";

import { CustomSelect } from "../components/CustomSelect";

import { useEffect, useState } from "react";
import { isDesktopApp } from "../desktop";
import { getDesktopAvatarMonitors, type DesktopMonitor } from "../desktop-avatar";
import { IconInterfaceSparkles as Sparkles, IconInterfaceRefresh as RefreshCw } from "../CustomIcons";

import { getAvatarOverlay, updateRuntimeSettings, sendAvatarTestEmotion, sendAvatarTestGesture, sendAvatarTestPhrase, stopAvatar, updateAvatarOverlay } from "../api";
import type { AvatarStatusResponse, AvatarOverlaySettings, AvatarPlacement, AvatarQuality, PublicSettings, InterfaceLocale } from "../types";

import { InfoRow } from "../components/InfoRow";

import { notify } from "../notifications";

import { animateButtonPress } from "../animations";

import { DevBadge, formatTime } from "./SettingsControls";
import { AppSwitch as SettingsSwitch } from "../components/AppSwitch";
const AVATAR_EMOTION_LABELS: Record<string, string> = {
  neutral: "Нейтральная", happy: "Радость", sad: "Грусть", angry: "Злость",
  annoyed: "Раздражение", smirk: "Ухмылка", thinking: "Задумчивость", surprised: "Удивление",
  embarrassed: "Смущение", concerned: "Обеспокоенность",
  playful: "Озорная / Игривая", pouting: "Надутые щёчки",
  wink: "Подмигивание (правый)", wink_left: "Подмигивание (левый)",
  skeptical: "Скептицизм", proud: "Гордость / Довольная", sleepy: "Сонная",
  excited: "Восторг", shocked: "Шок", touched: "Растроганная",
  teasing: "Дразнящая", relaxed: "Расслабленная", curious: "Любопытство", confused: "Озадаченная",
};
const AVATAR_GESTURE_LABELS: Record<string, string> = {
  greeting: "Приветствие (авто)", greeting_right: "Приветствие (правая рука)",
  greeting_left: "Приветствие (левая рука)", greeting_casual: "Приветствие (непринуждённое)",
  farewell: "Прощание (авто)", farewell_right: "Прощание (правая рука)",
  farewell_left: "Прощание (левая рука)", farewell_casual: "Прощание (спокойное)",
  talk: "Разговор (авто)", talk_right: "Разговор (правая рука)", talk_left: "Разговор (левая рука)",
  thinking: "Размышление (авто)", thinking_right: "Размышление (правая рука)", thinking_left: "Размышление (левая рука)",
  question: "Вопрос (авто)", question_right: "Вопрос (правая рука)", question_left: "Вопрос (левая рука)",
  explanation: "Объяснение (авто)", explanation_right: "Объяснение (правая рука)", explanation_left: "Объяснение (левая рука)",
  agreement: "Согласие", disagreement: "Несогласие",
  surprise: "Удивление", frustration: "Фрустрация", shrug: "Пожимание плечами", nod: "Кивок",
  head_scratch: "Почесать голову", clapping: "Аплодисменты", laughing: "Смех",
  thumbs_up: "Палец вверх", facepalm: "Фейспалм", pointing: "Указать пальцем", bow: "Поклон",
};

export function AvatarControls({
  diagnostics = false,
  avatarStatus,
  overlay: initialOverlay,
  placement,
  inAppVisible,
  inAppQuality,
  desktopQuality,
  interfaceLocale,
  developerMode = false,
  onUnlockRequest,
  onRefresh,
  onOverlayChanged,
  onSettingsChanged,
  onOpenQaStudio,
}: {
  diagnostics?: boolean;
  avatarStatus: AvatarStatusResponse | null;
  overlay: AvatarOverlaySettings | null;
  placement: AvatarPlacement;
  inAppVisible: boolean;
  inAppQuality: AvatarQuality;
  desktopQuality: AvatarQuality;
  interfaceLocale: InterfaceLocale;
  developerMode?: boolean;
  onUnlockRequest?: () => void;
  onRefresh: () => Promise<void>;
  onOverlayChanged: (overlay: AvatarOverlaySettings | null) => void;
  onSettingsChanged: (settings: PublicSettings) => void;
  onOpenQaStudio?: () => void;
}) {
  const defaultTestPhrase = interfaceLocale === "en" ? "Avatar test." : "Проверка аватара.";
  const [phrase, setPhrase] = useState(defaultTestPhrase);
  const [emotion, setEmotion] = useState("happy");
  const [gesture, setGesture] = useState("greeting");
  const [motionIntensity, setMotionIntensity] = useState(0.8);
  const [busy, setBusy] = useState(false);
  const [overlay, setOverlay] = useState<AvatarOverlaySettings | null>(initialOverlay);
  const [monitors, setMonitors] = useState<DesktopMonitor[]>([]);
  useEffect(() => {
    if (!isDesktopApp()) return;
    const refresh = () => void getDesktopAvatarMonitors().then(setMonitors).catch(() => {});
    refresh(); window.addEventListener("focus", refresh);
    return () => window.removeEventListener("focus", refresh);
  }, []);
  const enabled = Boolean(avatarStatus?.enabled);
  const client = avatarStatus?.clients[0];
  const engine = avatarStatus?.emotion_engine;

  useEffect(() => { setOverlay(initialOverlay); }, [initialOverlay]);
  useEffect(() => {
    setPhrase((current) => current === "Проверка аватара." || current === "Avatar test."
      ? defaultTestPhrase
      : current);
  }, [defaultTestPhrase]);
  useEffect(() => {
    if (initialOverlay) return;
    void getAvatarOverlay().then((nextOverlay) => {
      setOverlay(nextOverlay);
      onOverlayChanged(nextOverlay);
    }).catch(() => setOverlay(null));
  }, [initialOverlay, onOverlayChanged]);

  const run = async (action: () => Promise<unknown>, success: string) => {
    if (!developerMode) return;
    setBusy(true);
    try {
      await action();
      notify.success("Настройки", success);
      await onRefresh();
    } catch {
      notify.error("Настройки", "Не удалось выполнить действие с аватаром.");
    } finally {
      setBusy(false);
    }
  };

  const updateOverlay = async (patch: Partial<AvatarOverlaySettings>) => {
    setBusy(true);
    try {
      const nextOverlay = await updateAvatarOverlay(patch);
      setOverlay(nextOverlay);
      onOverlayChanged(nextOverlay);
      notify.success("Настройки", placement === "in_app" ? "Отображение аватара в диалоге обновлено." : "Настройки оверлея обновлены.");
    }
    catch { notify.error("Настройки", "Не удалось сохранить настройки оверлея."); }
    finally { setBusy(false); }
  };

  const updateInAppVisibility = async (visible: boolean) => {
    setBusy(true);
    try {
      const nextSettings = await updateRuntimeSettings({ avatar_in_app_visible: visible });
      onSettingsChanged(nextSettings);
      notify.success("Настройки", visible ? "Аватар будет показан в диалоге." : "Аватар скрыт в диалоге.");
    } catch (error) {
      notify.error("Настройки", error instanceof Error ? error.message : "Не удалось сохранить отображение аватара.");
    } finally { setBusy(false); }
  };

  const changeQuality = async (field: "avatar_in_app_quality" | "avatar_desktop_quality", quality: AvatarQuality) => {
    setBusy(true);
    try {
      const nextSettings = await updateRuntimeSettings({ [field]: quality });
      onSettingsChanged(nextSettings);
    } catch (error) {
      notify.error("Настройки", error instanceof Error ? error.message : "Не удалось сохранить качество аватара.");
    } finally {
      setBusy(false);
    }
  };

  const changePlacement = async (nextPlacement: AvatarPlacement) => {
    if (nextPlacement === placement) return;
    setBusy(true);
    try {
      const nextSettings = await updateRuntimeSettings({ avatar_placement: nextPlacement });
      onSettingsChanged(nextSettings);
      // The app-level effect owns the native transition. Keeping a single
      // caller avoids two concurrent Unity launches when this state update
      // re-renders the app.
      notify.success("Настройки", nextPlacement === "in_app"
        ? "Режим сохранён. Аватар появится внутри Iris на экране диалога."
        : "Режим сохранён. Аватар снова будет отдельным оверлеем на рабочем столе.");
    } catch (error) {
      notify.error("Настройки", error instanceof Error ? error.message : "Не удалось переключить размещение аватара.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="avatar-controls" aria-label="Управление аватаром">
      <div className="settings-card" hidden={diagnostics}>
        <div className="settings-card-header">
          <div className="settings-card-header-main">
            <div className="settings-card-title-group">
              <h2 className="settings-card-title">Управление аватаром</h2>
              <p className="settings-card-subtitle">Выберите, где показывать аватар Iris.</p>
            </div>
          </div>
          <div className="settings-card-header-actions">
            <span className={`settings-status-pill${enabled ? " is-active" : ""}`}>
              {enabled ? `${avatarStatus?.client_count ?? 0} подключено` : "Интеграция отключена"}
            </span>
            <MaterialButton materialKey={"App.button-41"} className="icon-button" onClick={() => void onRefresh()} disabled={busy} aria-label="Обновить статус аватара" title="Обновить статус аватара">
              <RefreshCw size={15} />
            </MaterialButton>
          </div>
        </div>

        <fieldset className="avatar-placement" disabled={busy}>
          <legend>Где показывать аватар</legend>
          <div className="avatar-placement-grid">
            <label className="avatar-placement-option">
              <input type="radio" name="avatar-placement" aria-label="Внутри Iris" checked={placement === "in_app"} onChange={() => void changePlacement("in_app")} />
              <span><strong>Внутри Iris</strong><small style={{ display: "block", color: "var(--color-text-muted)", marginTop: 2 }}>В левом нижнем углу диалога.</small></span>
            </label>
            <label className="avatar-placement-option">
              <input type="radio" name="avatar-placement" aria-label="На рабочем столе" checked={placement === "desktop_overlay"} onChange={() => void changePlacement("desktop_overlay")} />
              <span><strong>На рабочем столе</strong><small style={{ display: "block", color: "var(--color-text-muted)", marginTop: 2 }}>В отдельном окне поверх рабочего стола.</small></span>
            </label>
          </div>
        </fieldset>

        <div className="avatar-quality-settings">
          <h3 className="settings-card-title">Качество изображения</h3>
          <div className="avatar-quality-grid">
            <div>
              <label htmlFor="avatar-in-app-quality">Качество внутри Iris</label>
              <CustomSelect id="avatar-in-app-quality" value={inAppQuality} disabled={busy}
                onChange={event => void changeQuality("avatar_in_app_quality", event.target.value as AvatarQuality)}>
                <option value="low">Низкое</option><option value="medium">Среднее</option><option value="high">Высокое</option>
              </CustomSelect>
            </div>
            <div>
              <label htmlFor="avatar-desktop-quality">Качество на рабочем столе</label>
              <CustomSelect id="avatar-desktop-quality" value={desktopQuality} disabled={busy}
                onChange={event => void changeQuality("avatar_desktop_quality", event.target.value as AvatarQuality)}>
                <option value="low">Низкое</option><option value="medium">Среднее</option><option value="high">Высокое</option>
              </CustomSelect>
            </div>
          </div>
          <p className="settings-card-subtitle">Чем выше качество, тем ровнее контуры и больше нагрузка на видеокарту. Применяется сразу.</p>
        </div>

        <div className="avatar-options">
          <SettingsSwitch
            checked={placement === "in_app" ? inAppVisible : (overlay?.visible ?? true)}
            label={placement === "in_app" ? "Показывать в диалоге" : "Показывать на рабочем столе"}
            disabled={!enabled || busy}
            onChange={(checked) => void (placement === "in_app" ? updateInAppVisibility(checked) : updateOverlay({ visible: checked }))}
          />
          {placement === "desktop_overlay" && (
            <div className="avatar-overlay-options" style={{ display: "grid", gap: 6, width: "100%" }}>
              <fieldset className="avatar-placement" disabled={!enabled || busy}>
                <legend>Вид на рабочем столе</legend>
                <div className="avatar-placement-grid">
                  <label className="avatar-placement-option"><input type="radio" name="desktop-avatar-mode" checked={(overlay?.desktop_mode ?? "waist") === "waist"} onChange={() => void updateOverlay({desktop_mode:"waist"})}/>
                    <span><strong>По пояс</strong><small>Над панелью задач. Перемещение только по горизонтали.</small></span></label>
                  <label className="avatar-placement-option"><input type="radio" name="desktop-avatar-mode" checked={overlay?.desktop_mode === "full_body"} onChange={() => void updateOverlay({desktop_mode:"full_body"})}/>
                    <span><strong>В полный рост</strong><small>Свободное перемещение по рабочему столу.</small></span></label>
                </div>
              </fieldset>
              <label htmlFor="desktop-avatar-monitor">Монитор</label>
              <CustomSelect id="desktop-avatar-monitor" value={overlay?.layouts?.[overlay.desktop_mode ?? "waist"]?.monitor ?? overlay?.monitor ?? "primary"}
                disabled={!enabled || busy || monitors.length === 0} onChange={event => {
                  const mode=overlay?.desktop_mode ?? "waist";
                  const current=overlay?.layouts?.[mode];
                  const display=monitors.find(m=>m.id===event.target.value) ?? monitors.find(m=>m.primary);
                  void updateOverlay({layouts:{[mode]:{monitor:event.target.value,x_ratio:current?.x_ratio ?? 0.8,y_ratio:current?.y_ratio ?? 1,
                    height_dip:current?.height_dip ?? (display ? display.area.height/display.scale*0.7 : 520)}}});
                }}>
                <option value="primary">Основной монитор</option>
                {monitors.map((monitor,index)=><option key={monitor.id} value={monitor.id}>{`Монитор ${index+1} · ${monitor.name} · ${Math.round(monitor.area.width)} × ${Math.round(monitor.area.height)}${monitor.primary?" · основной":""}`}</option>)}
              </CustomSelect>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <small style={{ color: "var(--color-text-muted)" }}>Окно аватара</small>

              </div>
              <SettingsSwitch
                checked={overlay?.always_on_top ?? true}
                label="Поверх окон"
                disabled={!enabled || busy}
                onChange={(checked) => void updateOverlay({ always_on_top: checked })}
              />
              <SettingsSwitch
                checked={overlay?.locked ?? true}
                label="Закрепить положение и размер"
                disabled={!enabled || busy}
                onChange={(checked) => void updateOverlay({ locked: checked })}
              />
              <p className="settings-card-subtitle">Наведите на Iris и снимите замок, чтобы переместить её или изменить размер угловым маркером. Положение и размер каждого вида сохраняются отдельно.</p>
              <SettingsSwitch checked={overlay?.subtitles_enabled ?? true} label="Показывать субтитры" disabled={!enabled || busy}
                onChange={checked => void updateOverlay({subtitles_enabled:checked})}/>
              <label htmlFor="desktop-avatar-subtitles">Положение субтитров</label>
              <CustomSelect id="desktop-avatar-subtitles" value={overlay?.subtitle_position ?? "above"} disabled={!enabled || busy || overlay?.subtitles_enabled === false}
                onChange={event => void updateOverlay({subtitle_position:event.target.value as "above"|"below"|"left"|"right"})}>
                <option value="above">Над аватаром</option><option value="below">Под аватаром</option><option value="left">Слева</option><option value="right">Справа</option>
              </CustomSelect>
              <p className="settings-card-subtitle">Не больше двух строк, даже без наведения. У края экрана субтитры переходят на свободную сторону.</p>
            </div>
          )}
        </div>
      </div>

      <div hidden={!diagnostics || !developerMode} className="settings-card avatar-qa-studio-callout">
        <div>
          <strong style={{ display: "flex", alignItems: "center", gap: 6, color: "#fff", fontSize: "13.5px" }}>
            <Sparkles size={15} style={{ color: "#a78bfa" }} />
            Окно тестирования (QA Studio)
          </strong>
          <span style={{ display: "block", color: "rgba(255, 255, 255, 0.65)", fontSize: "12px", marginTop: 2 }}>
            Проверка эмоций, жестов, речи и уведомлений в отдельном окне.
          </span>
        </div>
        <MaterialButton materialKey={"App.button-42"}
          type="button"
          className="primary-button"
          onClick={() => onOpenQaStudio?.()}
          style={{ padding: "8px 16px", borderRadius: "10px", fontSize: "12px", display: "inline-flex", alignItems: "center", gap: "6px" }}
        >
          <Sparkles size={14} />
          Открыть окно тестирования
        </MaterialButton>
      </div>

      <Disclosure materialKey="avatar.technical" label="Технические данные" actions={<DevBadge active={developerMode} onClick={onUnlockRequest} />} hidden={!diagnostics} className="settings-technical-details">
        <div className="avatar-summary-grid">
          <InfoRow label="Клиент" value={client?.client_name ?? "не подключён"} />
          <InfoRow label="Состояние" value={client?.state ?? "Отключён"} />
          <InfoRow label="Последний сигнал" value={client ? formatTime(client.last_heartbeat_at) : "—"} />
          <InfoRow label="Целевая эмоция" value={engine?.target_emotion ?? "нейтральная"} />
        </div>


        <div className="avatar-grid" style={{ marginTop: 14 }}>
          <InfoRow label="Протокол" value={avatarStatus ? `v${avatarStatus.protocol_version}` : "недоступен"} />
          <InfoRow label="Профиль движения" value={client?.current_motion_profile ?? "нет данных"} />
          <InfoRow label="Текущий жест" value={client?.current_gesture ?? "нет"} />
          <InfoRow label="Связь с движком" value={engine ? (engine.mapping_valid ? "настроена" : "резервная") : "недоступна"} />
        </div>
      </Disclosure>

      <Disclosure materialKey="avatar.test" label="Тест эмоций и жестов" actions={<DevBadge active={developerMode} onClick={onUnlockRequest} />} hidden={!diagnostics || !developerMode} className="settings-technical-details">
        <div className={`avatar-test-grid${!developerMode ? " dev-locked-field" : ""}`} style={{ marginTop: 14 }}>
        <label>
          Тестовая фраза
          <input value={phrase} onChange={(event) => setPhrase(event.target.value)} disabled={!enabled || busy || !developerMode} />
        </label>
        <label>
          Эмоция
          <CustomSelect value={emotion} onChange={(event) => setEmotion(event.target.value)} disabled={!enabled || busy || !developerMode}>
            {Object.entries(AVATAR_EMOTION_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </CustomSelect>
        </label>
        <label>
          Тестовый жест
          <CustomSelect value={gesture} onChange={(event) => setGesture(event.target.value)} disabled={!enabled || busy || !developerMode}>
            {Object.entries(AVATAR_GESTURE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </CustomSelect>
        </label>
        <label>
          Интенсивность движения {motionIntensity.toFixed(1)}
          <input min="0" max="1" step="0.1" type="range" value={motionIntensity} onChange={(event) => setMotionIntensity(Number(event.target.value))} disabled={!enabled || busy || !developerMode} />
        </label>
        </div>
        <div className="avatar-test-actions" style={{ marginTop: 16 }}>
          <MaterialButton materialKey={"App.button-43"} className="primary-button" onClick={(e) => { animateButtonPress(e.currentTarget); void run(() => sendAvatarTestPhrase({ text: phrase, emotion }), "Тестовая фраза отправлена."); }} disabled={!enabled || busy || !developerMode || !phrase.trim()}>Отправить фразу</MaterialButton>
          <MaterialButton materialKey={"App.button-44"} className="secondary" onClick={(e) => { animateButtonPress(e.currentTarget); void run(() => sendAvatarTestEmotion({ emotion, intensity: 1 }), "Эмоция отправлена."); }} disabled={!enabled || busy || !developerMode}>Отправить эмоцию</MaterialButton>
          <MaterialButton materialKey={"App.button-45"} className="secondary" onClick={(e) => { animateButtonPress(e.currentTarget); void run(() => sendAvatarTestGesture({ gesture, intensity: motionIntensity, interrupt: true }), "Тестовый жест отправлен."); }} disabled={!enabled || busy || !developerMode}>Отправить жест</MaterialButton>
          <MaterialButton materialKey={"App.button-46"} className="secondary" onClick={(e) => { animateButtonPress(e.currentTarget); void run(stopAvatar, "Движение сброшено."); }} disabled={!enabled || busy || !developerMode}>Сбросить движение</MaterialButton>
        </div>
      </Disclosure>
    </section>
  );
}
