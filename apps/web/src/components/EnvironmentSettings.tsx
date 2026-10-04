import { MaterialButton } from "./MaterialButton";
import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowUpRight } from "lucide-react";
import { getEnvironmentStatus } from "../api";
import { AppSwitch } from "./AppSwitch";
import { CustomSelect } from "./CustomSelect";
import type { EnvironmentStatus, PublicSettings } from "../types";
import type { RuntimeSettingsPatch } from "../settingsAutosave";

export interface EnvironmentSettingsProps {
  settings: PublicSettings;
  developerMode: boolean;
  onSaveSetting: (patch: RuntimeSettingsPatch, rollback?: () => void,
    committed?: (settings: PublicSettings) => void) => Promise<boolean>;
  onOpenApiKeys: () => void;
}

export function EnvironmentSettings({ settings, developerMode, onSaveSetting, onOpenApiKeys }: EnvironmentSettingsProps) {
  const [envStatus, setEnvStatus] = useState<EnvironmentStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [cityInput, setCityInput] = useState(settings.location_city ?? "");
  const [citySaved, setCitySaved] = useState(false);
  const [cityBusy, setCityBusy] = useState(false);
  const cityDraft = useRef(cityInput);
  const cityDirty = useRef(false);
  const citySaving = useRef(false);
  const requestId = useRef(0);
  const locationMode = settings.location_mode ?? "auto";
  const weatherEnabled = settings.weather_enabled ?? true;
  const newsEnabled = settings.news_enabled ?? true;
  const webSearchEnabled = settings.web_search_enabled ?? true;
  const searchProvider = settings.web_search_provider === "tavily" ? "tavily" : "free";
  const newsCategory = settings.news_category ?? "all";

  const refreshStatus = useCallback(async () => {
    const id = ++requestId.current;
    setLoading(true);
    try {
      const data = await getEnvironmentStatus();
      if (id === requestId.current) setEnvStatus(data);
    } catch {
      if (id === requestId.current) setEnvStatus(null);
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  }, []);
  useEffect(() => {
    void refreshStatus();
    return () => { requestId.current += 1; };
  }, [refreshStatus]);
  useEffect(() => {
    if (!cityDirty.current) {
      const city = settings.location_city ?? "";
      setCityInput(city);
      cityDraft.current = city;
    }
  }, [settings.location_city]);

  const saveSetting = (patch: RuntimeSettingsPatch) => {
    void onSaveSetting(patch, undefined, () => { void refreshStatus(); });
  };
  const handleSaveCity = async () => {
    const trimmed = cityDraft.current.trim();
    if (!trimmed || citySaving.current) return;
    citySaving.current = true;
    setCityBusy(true);
    setCitySaved(false);
    try {
      await onSaveSetting({ location_city: trimmed }, undefined, next => {
        if (cityDraft.current.trim() === trimmed) {
          cityDirty.current = false;
          cityDraft.current = next.location_city ?? trimmed;
          setCityInput(cityDraft.current);
          setCitySaved(true);
        }
        void refreshStatus();
      });
    } finally {
      citySaving.current = false;
      setCityBusy(false);
    }
  };

  const unavailable = loading ? "Загрузка…" : "Данные недоступны";
  const location = envStatus?.location;
  const sources: Record<string, string> = {
    manual: "вручную", ip_auto: "по IP", timezone_fallback: "примерно, по часовому поясу", unknown: "не определён",
  };
  const locationLabel = location?.city ? `${location.city} (${sources[location.source] ?? "источник не определён"})` : unavailable;
  const timeLabel = envStatus?.time ? `${envStatus.time.formatted_time}, ${envStatus.time.weekday}` : unavailable;
  const weatherLabel = envStatus?.weather
    ? `${envStatus.weather.temperature > 0 ? "+" : ""}${Math.round(envStatus.weather.temperature)}°C, ${envStatus.weather.condition}`
    : unavailable;

  return <>
    <section className="settings-card" aria-labelledby="environment-location">
      <div className="settings-card-header"><div className="settings-card-header-main"><div className="settings-card-title-group">
        <h3 className="settings-card-title" id="environment-location">Местоположение и время</h3>
        <p className="settings-card-subtitle">Город для погоды и контекста бесед. Время берётся из системных часов.</p>
      </div></div></div>
      <div className="settings-card-grid">
        <div className="readonly-setting"><span>Время на устройстве</span><strong>{timeLabel}</strong></div>
        <div className="readonly-setting"><span>Текущий город</span><strong>{locationLabel}</strong></div>
      </div>
      <label>Режим определения города
        <CustomSelect value={locationMode} onChange={event => saveSetting({ location_mode: event.target.value as "auto" | "manual" })}>
          <option value="auto">Автоматически (по IP и часовому поясу)</option>
          <option value="manual">Указать город вручную</option>
        </CustomSelect>
        <small>{locationMode === "auto" ? "Город определяется по IP; часовой пояс даёт приблизительное местоположение."
          : "Укажите город для прогноза погоды. Системное время при этом не меняется."}</small>
      </label>
      {locationMode === "manual" && <div className="settings-city-field">
        <label htmlFor="environment-city">Город</label>
        <div className="settings-input-group">
          <input id="environment-city" type="text" value={cityInput} maxLength={100} placeholder="Например: Москва, Санкт-Петербург, Сочи…"
            onChange={event => {
              cityDraft.current = event.target.value;
              cityDirty.current = true;
              setCityInput(event.target.value);
              setCitySaved(false);
            }} onKeyDown={event => {
              if (event.key === "Enter") { event.preventDefault(); void handleSaveCity(); }
            }} />
          <MaterialButton materialKey="environment.city.save" type="button" className="secondary"
            disabled={cityBusy || !cityInput.trim()} onClick={() => void handleSaveCity()}>
            {cityBusy ? "Сохраняем…" : citySaved ? "Сохранено ✓" : "Сохранить"}
          </MaterialButton>
        </div>
        <small>Нажмите Enter или «Сохранить», чтобы применить город.</small>
      </div>}
    </section>

    <section className="settings-card" aria-labelledby="environment-weather">
      <div className="settings-card-header"><div className="settings-card-title-group">
        <h3 className="settings-card-title" id="environment-weather">Погода</h3>
        <p className="settings-card-subtitle">Текущая погода и прогноз для выбранного города.</p>
      </div></div>
      <AppSwitch checked={weatherEnabled} label="Погода за окном"
        description="Iris получает текущую погоду, а при вопросе запрашивает подробный прогноз."
        onChange={checked => saveSetting({ weather_enabled: checked })} />
      {weatherEnabled && <div className="readonly-setting"><span>Погода сейчас</span><strong>{weatherLabel}</strong></div>}
    </section>

    <section className="settings-card" aria-labelledby="environment-news">
      <div className="settings-card-header"><div className="settings-card-title-group">
        <h3 className="settings-card-title" id="environment-news">Новости</h3>
        <p className="settings-card-subtitle">Свежие события из открытых RSS-лент.</p>
      </div></div>
      <AppSwitch checked={newsEnabled} label="Сводка новостей"
        description="Россия и мир, технологии, наука и игры. В беседу попадают новости по теме вопроса."
        onChange={checked => saveSetting({ news_enabled: checked })} />
      {newsEnabled && <label>Категория новостей
        <CustomSelect value={newsCategory} onChange={event => saveSetting({ news_category: event.target.value as NonNullable<PublicSettings["news_category"]> })}>
          <option value="all">Все категории</option><option value="tech">Технологии и IT</option>
          <option value="general">Россия и мир</option><option value="science">Наука и космос</option><option value="games">Игры</option>
        </CustomSelect>
        <small>Ленты обновляются в фоне. API-ключ для новостей не требуется.</small>
      </label>}
    </section>

    <section className="settings-card" aria-labelledby="environment-search">
      <div className="settings-card-header"><div className="settings-card-title-group">
        <h3 className="settings-card-title settings-target-heading" id="environment-search" tabIndex={-1}>Веб-поиск</h3>
        <p className="settings-card-subtitle">Проверка актуальной информации во время разговора.</p>
      </div></div>
      <AppSwitch checked={webSearchEnabled} label="Самостоятельный поиск в интернете"
        description="Запросы и источники сохраняются только в истории диалога."
        onChange={checked => saveSetting({ web_search_enabled: checked })} />
      <label>Источник веб-поиска
        <CustomSelect value={searchProvider} disabled={!webSearchEnabled} onChange={event => saveSetting({ web_search_provider: event.target.value as "free" | "tavily" })}>
          <option value="free">Бесплатные источники</option><option value="tavily">Tavily Free</option>
        </CustomSelect>
        <small>При отсутствии ключа Tavily или исчерпании бесплатной квоты Iris использует открытые источники.</small>
      </label>
      <div className="settings-source-key-row">
        <span>{settings.search_api_keys_configured?.tavily ? "Ключ Tavily настроен" : "Ключ Tavily не настроен"}</span>
        <MaterialButton materialKey="environment.open-api-keys" type="button" className="text-button settings-inline-link" onClick={onOpenApiKeys}>
          Настроить API-ключ<ArrowUpRight size={15} aria-hidden="true" />
        </MaterialButton>
      </div>
    </section>

    <div className="readonly-setting audio-device-refresh">
      <span>Данные окружения</span>
      <MaterialButton materialKey="environment.refresh" type="button" className="secondary" disabled={loading} onClick={() => void refreshStatus()}>
        {loading ? "Обновляем…" : "Обновить данные"}
      </MaterialButton>
      {!loading && (!envStatus || envStatus.status === "unavailable") && <small role="status">Окружение пока недоступно. Попробуйте обновить данные.</small>}
    </div>
    {developerMode && envStatus?.ambient_header && <div className="readonly-setting dev-locked-field">
      <span>Промпт контекста (режим разработчика)</span><small className="settings-environment-prompt">{envStatus.ambient_header}</small>
    </div>}
  </>;
}
