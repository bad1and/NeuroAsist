import { MaterialButton } from "./MaterialButton";
import { useCallback, useEffect, useState } from "react";
import { getEnvironmentStatus, updateRuntimeSettings, isDesktopManaged, saveDesktopSearchApiKey,
  removeDesktopSearchApiKey, checkSearchProvider, getSettings } from "../api";
import type { SearchApiProvider } from "../api";
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
  const [webSearchEnabled, setWebSearchEnabled] = useState(settings.web_search_enabled ?? true);
  const [searchProvider, setSearchProvider] = useState<NonNullable<PublicSettings["web_search_provider"]>>(settings.web_search_provider ?? "free");
  const [keyProvider, setKeyProvider] = useState<SearchApiProvider>("brave");
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [apiBusy, setApiBusy] = useState(false);
  const [apiMessage, setApiMessage] = useState("");
  const [newsCategory, setNewsCategory] = useState<NonNullable<PublicSettings["news_category"]>>(
    settings.news_category ?? "all"
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

  useEffect(() => {
    setSearchProvider(settings.web_search_provider ?? "free");
  }, [settings.web_search_provider]);

  const handleSearchKey = async (action: "save" | "remove" | "check") => {
    setApiBusy(true);
    setApiMessage("");
    try {
      if (action === "check") {
        const result = await checkSearchProvider(keyProvider);
        const messages: Record<string, string> = {
          ok: "Подключение работает.", unconfigured: "Сначала сохраните ключ.",
          unauthorized: "Ключ не принят сервисом.", blocked: "Сервис ограничил запросы или закончилась квота.",
          cooldown: "Сервис временно ограничен. Повторите позже.", timeout: "Сервис не ответил вовремя.",
          empty: "Сервис ответил без результатов.",
        };
        setApiMessage(messages[result.status] ?? "Проверка подключения не удалась.");
      } else {
        if (action === "save") await saveDesktopSearchApiKey(keyProvider, apiKeyInput.trim());
        else await removeDesktopSearchApiKey(keyProvider);
        setApiKeyInput("");
        // Credential commands restart the core; retry readiness, not saving.
        for (let attempt = 0; attempt < 20; attempt += 1) {
          try {
            onSettingsChanged(await getSettings());
            break;
          } catch {
            if (attempt === 19) throw new Error("Ядро ещё запускается.");
            await new Promise((resolve) => setTimeout(resolve, 500));
          }
        }
        setApiMessage(action === "save" ? "Ключ сохранён. Режим поиска не изменён." : "Ключ удалён.");
      }
    } catch {
      setApiMessage("Не удалось выполнить действие. Проверьте подключение к Iris.");
    } finally {
      setApiBusy(false);
    }
  };

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
      {/* Location Settings Card */}
      <div className="settings-card">
        <div className="settings-card-header">
          <div className="settings-card-header-main">
            <div className="settings-card-title-group">
              <h3 className="settings-card-title">Местоположение и время</h3>
              <p className="settings-card-subtitle">Определение города и времени для прогноза погоды и контекста бесед</p>
            </div>
          </div>
        </div>

        <div className="settings-card-grid">
          <div className="readonly-setting">
            <span>Местное время</span>
            <strong>{timeLabel}</strong>
          </div>

          <div className="readonly-setting">
            <span>Текущий город</span>
            <strong>{locationLabel}</strong>
          </div>
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
            <div className="settings-input-group">
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
              <MaterialButton materialKey={"EnvironmentSettings.button-1"}
                type="button"
                className="secondary"
                onClick={() => void handleSaveCity()}
              >
                {citySaved ? "Сохранено ✓" : "Сохранить"}
              </MaterialButton>
            </div>
            <small>Нажмите Enter или «Сохранить», чтобы применить город.</small>
          </label>
        )}
      </div>

      {/* Weather & News Switches Card */}
      <div className="settings-card">
        <div className="settings-card-header">
          <div className="settings-card-header-main">
            <div className="settings-card-title-group">
              <h3 className="settings-card-title">Данные и внешние источники</h3>
              <p className="settings-card-subtitle">Погода, новости и самостоятельная проверка информации по открытым источникам</p>
            </div>
          </div>
        </div>

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
          checked={webSearchEnabled}
          label="Самостоятельный поиск в интернете"
          description="Iris может незаметно проверить актуальные сведения во время ответа. Запросы и источники сохраняются только в истории диалога."
          onChange={(checked) => {
            setWebSearchEnabled(checked);
            void saveSetting({ web_search_enabled: checked });
          }}
        />

        <AppSwitch
          checked={newsEnabled}
          label="Сводка новостей"
          description="Свежие события России и мира, технологии, наука и игры из открытых RSS-лент."
          onChange={(checked) => {
            setNewsEnabled(checked);
            void saveSetting({ news_enabled: checked });
          }}
        />

        {newsEnabled && (
          <label>
            Категория новостей
            <CustomSelect value={newsCategory} onChange={(e) => {
              const next = e.target.value as NonNullable<PublicSettings["news_category"]>;
              setNewsCategory(next);
              void saveSetting({ news_category: next });
            }}>
              <option value="all">Все категории</option>
              <option value="tech">Технологии и IT</option>
              <option value="general">Россия и мир</option>
              <option value="science">Наука и космос</option>
              <option value="games">Игры</option>
            </CustomSelect>
            <small>Ленты обновляются в фоне. В диалог попадают только новости по теме вашего вопроса.</small>
          </label>
        )}

        <label>
          Источник веб-поиска
          <CustomSelect value={searchProvider} disabled={apiBusy} onChange={async (event) => {
            const next = event.target.value as NonNullable<PublicSettings["web_search_provider"]>;
            setApiMessage("");
            try {
              const updated = await updateRuntimeSettings({ web_search_provider: next });
              setSearchProvider(updated.web_search_provider ?? "free");
              onSettingsChanged(updated);
            } catch {
              setApiMessage("Не удалось сохранить режим поиска.");
            }
          }}>
            <option value="free">Бесплатные источники</option>
            <option value="brave">Brave Search API</option>
            <option value="tavily">Tavily API</option>
            <option value="serper">Serper API</option>
          </CustomSelect>
          <small>По умолчанию поиск бесплатный. API используется только после вашего выбора; при ошибке Iris обращается к бесплатным источникам.</small>
        </label>

        <details>
          <summary>Собственный поисковый API</summary>
          <label>
            Сервис для подключения
            <CustomSelect value={keyProvider} disabled={apiBusy} onChange={(event) => {
              setKeyProvider(event.target.value as SearchApiProvider);
              setApiKeyInput("");
              setApiMessage("");
            }}>
              <option value="brave">Brave</option>
              <option value="tavily">Tavily</option>
              <option value="serper">Serper</option>
            </CustomSelect>
          </label>
          <label>
            API-ключ поискового сервиса
            <input type="password" autoComplete="off" value={apiKeyInput} disabled={apiBusy || !isDesktopManaged()}
              onChange={(event) => setApiKeyInput(event.target.value)} />
            <small>{settings.search_api_keys_configured?.[keyProvider] ? "Ключ сохранён в Windows Credential Manager." : "Ключ не подключён."}</small>
          </label>
          <div className="settings-input-group" style={{ flexWrap: "wrap" }}>
            <MaterialButton materialKey="EnvironmentSettings.search-save" className="secondary" disabled={apiBusy || !apiKeyInput.trim() || !isDesktopManaged()} onClick={() => void handleSearchKey("save")}>Сохранить ключ</MaterialButton>
            <MaterialButton materialKey="EnvironmentSettings.search-remove" className="secondary" disabled={apiBusy || !settings.search_api_keys_configured?.[keyProvider] || !isDesktopManaged()} onClick={() => void handleSearchKey("remove")}>Удалить ключ</MaterialButton>
            <MaterialButton materialKey="EnvironmentSettings.search-check" className="secondary" disabled={apiBusy || !settings.search_api_keys_configured?.[keyProvider]} onClick={() => void handleSearchKey("check")}>Проверить подключение</MaterialButton>
          </div>
          <small>{isDesktopManaged() ? "Ключи сервисов независимы. Сохранение ключа не включает API. Проверка отправляет один запрос выбранному сервису." : "Управление ключами доступно в установленном приложении Iris."}</small>
        </details>
        {apiMessage && <p role="status">{apiMessage}</p>}

        <div className="readonly-setting audio-device-refresh">
          <span>Данные окружения</span>
          <MaterialButton materialKey={"EnvironmentSettings.button-2"}
            className="secondary"
            type="button"
            onClick={() => void refreshStatus()}
            disabled={loading}
          >
            {loading ? "Обновляем…" : "Обновить данные"}
          </MaterialButton>
        </div>

        {developerMode && envStatus?.ambient_header && (
          <div className="readonly-setting dev-locked-field">
            <span>Промпт контекста (режим разработчика)</span>
            <small style={{ fontFamily: "var(--font-mono)", fontSize: "11px", wordBreak: "break-all" }}>
              {envStatus.ambient_header}
            </small>
          </div>
        )}
      </div>
    </>
  );
}
