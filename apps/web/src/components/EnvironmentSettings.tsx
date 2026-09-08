import { useCallback, useEffect, useState } from "react";
import { getEnvironmentStatus, updateRuntimeSettings } from "../api";
import { AppSwitch } from "./AppSwitch";
import { CustomSelect } from "./CustomSelect";
import type { EnvironmentStatus, PublicSettings } from "../types";

export interface EnvironmentSettingsProps {
  settings: PublicSettings;
  developerMode: boolean;
  onSettingsChanged: (nextSettings: PublicSettings) => void;
}

export function EnvironmentSettings({
  settings,
  developerMode,
  onSettingsChanged,
}: EnvironmentSettingsProps) {
  const [envStatus, setEnvStatus] = useState<EnvironmentStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [cityInput, setCityInput] = useState(settings.location_city ?? "");
  const [citySaved, setCitySaved] = useState(false);
  const [locationMode, setLocationMode] = useState<"auto" | "manual">(
    (settings.location_mode as "auto" | "manual") ?? "auto"
  );
  const [weatherEnabled, setWeatherEnabled] = useState(settings.weather_enabled ?? true);
  const [newsEnabled, setNewsEnabled] = useState(settings.news_enabled ?? true);
  const [newsCategory, setNewsCategory] = useState<"all" | "general" | "tech">(
    (settings.news_category as "all" | "general" | "tech") ?? "all"
  );

  const refreshStatus = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getEnvironmentStatus();
      setEnvStatus(data);
    } catch {
      // Ignored: silent refresh fallback
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshStatus();
  }, [refreshStatus]);

  const saveSetting = useCallback(
    async (patch: Parameters<typeof updateRuntimeSettings>[0]) => {
      try {
        const next = await updateRuntimeSettings(patch);
        onSettingsChanged(next);
        void refreshStatus();
      } catch {
        // Ignored: standard error handler
      }
    },
    [onSettingsChanged, refreshStatus]
  );

  const handleSaveCity = async () => {
    const trimmed = cityInput.trim();
    await saveSetting({ location_city: trimmed });
    setCitySaved(true);
    setTimeout(() => setCitySaved(false), 2000);
  };

  const weatherLabel = envStatus?.weather
    ? `${envStatus.weather.temperature > 0 ? "+" : ""}${Math.round(envStatus.weather.temperature)}°C, ${envStatus.weather.condition}`
    : weatherEnabled
      ? "Загрузка…"
      : "Выключена";

  const locationLabel = envStatus?.location.city
    ? `${envStatus.location.city} (${envStatus.location.source === "manual" ? "вручную" : "авто"})`
    : "Определение…";

  const timeLabel = envStatus?.time
    ? `${envStatus.time.formatted_time}, ${envStatus.time.weekday}`
    : "Определение…";

  return (
    <>
      {/* Location Settings */}
      <fieldset className="settings-group">
        <legend>Местоположение</legend>

        <div className="readonly-setting">
          <span>Местное время</span>
          <strong>{timeLabel}</strong>
        </div>

        <div className="readonly-setting">
          <span>Текущий город</span>
          <strong>{locationLabel}</strong>
        </div>

        <label>
          Режим определения города
          <CustomSelect
            value={locationMode}
            onChange={(e) => {
              const next = e.target.value as "auto" | "manual";
              setLocationMode(next);
              void saveSetting({ location_mode: next });
            }}
          >
            <option value="auto">Автоматически (по IP и часовому поясу)</option>
            <option value="manual">Указать город вручную</option>
          </CustomSelect>
          <small>
            {locationMode === "auto"
              ? "Iris определяет город по сетевому адресу и часовому поясу Windows."
              : "Вы можете указать любой город мира для прогноза погоды."}
          </small>
        </label>

        {locationMode === "manual" && (
          <label>
            Город
            <div style={{ display: "flex", gap: "8px" }}>
              <input
                type="text"
                value={cityInput}
                placeholder="Например: Москва, Санкт-Петербург, Сочи..."
                onChange={(e) => {
                  setCityInput(e.target.value);
                  setCitySaved(false);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    void handleSaveCity();
                  }
                }}
              />
              <button
                type="button"
                className="secondary"
                onClick={() => void handleSaveCity()}
              >
                {citySaved ? "Сохранено ✓" : "Сохранить"}
              </button>
            </div>
            <small>Нажмите Enter или «Сохранить», чтобы применить город.</small>
          </label>
        )}
      </fieldset>

      {/* Weather & News Switches */}
      <fieldset className="settings-group">
        <legend>Данные и внешние источники</legend>

        {weatherEnabled && (
          <div className="readonly-setting">
            <span>Погода за окном</span>
            <strong>{weatherLabel}</strong>
          </div>
        )}

        <AppSwitch
          checked={weatherEnabled}
          label="Погода за окном"
          description="Iris всегда знает текущую температуру и погоду, а при вопросе даёт подробный прогноз на 3 дня."
          onChange={(checked) => {
            setWeatherEnabled(checked);
            void saveSetting({ weather_enabled: checked });
          }}
        />

        <AppSwitch
          checked={newsEnabled}
          label="Сводка новостей"
          description="Позволяет Iris отвечать на вопросы о главных событиях в мире и сфере технологий по свежим открытым RSS-лентам."
          onChange={(checked) => {
            setNewsEnabled(checked);
            void saveSetting({ news_enabled: checked });
          }}
        />

        {newsEnabled && (
          <label>
            Категория новостей
            <CustomSelect
              value={newsCategory}
              onChange={(e) => {
                const next = e.target.value as "all" | "general" | "tech";
                setNewsCategory(next);
                void saveSetting({ news_category: next });
              }}
            >
              <option value="all">Все (Общие + Технологии)</option>
              <option value="tech">Технологии и IT (Хабр, 3DNews)</option>
              <option value="general">Общие мировые новости (РБК, Google News)</option>
            </CustomSelect>
            <small>Новости передаются только тогда, когда вы сами спрашиваете о них в диалоге.</small>
          </label>
        )}

        <div className="readonly-setting audio-device-refresh">
          <span>Данные окружения</span>
          <button
            className="secondary"
            type="button"
            onClick={() => void refreshStatus()}
            disabled={loading}
          >
            {loading ? "Обновляем…" : "Обновить данные"}
          </button>
        </div>

        {developerMode && envStatus?.ambient_header && (
          <div className="readonly-setting dev-locked-field">
            <span>Промпт контекста (режим разработчика)</span>
            <small style={{ fontFamily: "var(--font-mono)", fontSize: "11px", wordBreak: "break-all" }}>
              {envStatus.ambient_header}
            </small>
          </div>
        )}
      </fieldset>
    </>
  );
}

