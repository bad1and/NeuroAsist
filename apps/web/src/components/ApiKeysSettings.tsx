import { useEffect, useRef, useState } from "react";
import { ExternalLink } from "lucide-react";
import {
  checkSearchProvider, getSettings, removeDesktopApiKey, removeDesktopCodingApiKey,
  removeDesktopSearchApiKey, saveDesktopApiKey, saveDesktopCodingApiKey, saveDesktopSearchApiKey,
} from "../api";
import { isDesktopApp, openApiKeyPortal } from "../desktop";
import type { PublicSettings } from "../types";
import { MaterialButton } from "./MaterialButton";

export type CredentialTarget = "deepseek" | "coding" | "tavily";
type Credential = CredentialTarget | "brave" | "serper";
const CHECK_MESSAGES: Record<string, string> = {
  ok: "Подключение работает.", unconfigured: "Сначала сохраните ключ.",
  unauthorized: "Ключ не принят сервисом.", blocked: "Сервис ограничил запросы или закончилась квота.",
  cooldown: "Сервис временно ограничен. Повторите позже.", timeout: "Сервис не ответил вовремя.",
  empty: "Сервис ответил без результатов.", unavailable: "Поисковый сервис пока недоступен.",
  free_only: "Этот сервис исключён из строго бесплатного режима.",
  unverified_free_plan: "Бесплатный тариф без оплаты сверх пакета не подтверждён. Используются открытые источники.",
  quota_exhausted: "Лимит бесплатного поиска исчерпан. Iris продолжает через открытые источники.",
  budget_unavailable: "Не удалось проверить локальный лимит. Используются открытые источники.",
};
const DETAILS: Record<Credential, { title: string; label: string; description: string }> = {
  deepseek: { title: "DeepSeek API", label: "API-ключ DeepSeek", description: "Диалог, память и фоновые ответы Iris." },
  coding: { title: "Coding Agent API", label: "API-ключ Coding Agent", description: "Отдельный ключ DeepSeek для задач с кодом." },
  tavily: { title: "Tavily API", label: "API-ключ Tavily", description: "Веб-поиск на бесплатном тарифе. Без ключа работают открытые источники." },
  brave: { title: "Brave API", label: "API-ключ Brave", description: "Сервис сейчас не используется. Ранее сохранённый ключ можно удалить." },
  serper: { title: "Serper API", label: "API-ключ Serper", description: "Сервис сейчас не используется. Ранее сохранённый ключ можно удалить." },
};

export function ApiKeysSettings({ settings, active, onSettingsChanged }:
  { settings: PublicSettings; active: boolean; onSettingsChanged: (settings: PublicSettings) => void }) {
  const [inputs, setInputs] = useState<Partial<Record<Credential, string>>>({});
  const [messages, setMessages] = useState<Partial<Record<Credential, { text: string; error?: boolean }>>>({});
  const [busy, setBusy] = useState<Credential | null>(null);
  const busyRef = useRef(false);
  const desktop = isDesktopApp();
  const openPortal = async (kind: CredentialTarget) => {
    try { await openApiKeyPortal(kind === "tavily" ? "tavily" : "deepseek"); }
    catch { setMessages(current => ({ ...current, [kind]: { text: "Не удалось открыть кабинет сервиса. Попробуйте ещё раз.", error: true } })); }
  };
  useEffect(() => { if (!active) setInputs({}); }, [active]);
  const configured = (kind: Credential) => kind === "deepseek" ? settings.api_key_configured
    : kind === "coding" ? settings.coding_api_key_configured : Boolean(settings.search_api_keys_configured?.[kind]);

  const act = async (kind: Credential, action: "save" | "remove" | "check") => {
    if (busyRef.current) return;
    const value = inputs[kind]?.trim() ?? "";
    if (action === "save" && !value) return;
    busyRef.current = true;
    setBusy(kind);
    setMessages(current => ({ ...current, [kind]: undefined }));
    const message = (text: string, error = false) => setMessages(current => ({ ...current, [kind]: { text, error } }));
    try {
      if (action === "check") {
        const result = await checkSearchProvider("tavily");
        message((CHECK_MESSAGES[result.status] ?? "Проверка подключения не удалась.") +
          (result.quota?.used !== undefined ? ` Расход: ${result.quota.used} / ${result.quota.limit}.` : ""), result.status !== "ok");
        return;
      }
      if (action === "save") {
        if (kind === "deepseek") await saveDesktopApiKey(value);
        else if (kind === "coding") await saveDesktopCodingApiKey(value);
        else await saveDesktopSearchApiKey(kind, value);
      } else {
        if (kind === "deepseek") await removeDesktopApiKey();
        else if (kind === "coding") await removeDesktopCodingApiKey();
        else await removeDesktopSearchApiKey(kind);
      }
      setInputs(current => ({ ...current, [kind]: "" }));
      const success = action === "save" ? "Ключ сохранён в защищённом хранилище Windows." : "Ключ удалён.";
      message(`${success} Ожидаем запуск ядра…`);
      // Retry reads only: credential commands restart the core and must not be replayed.
      for (let attempt = 0; attempt < 20; attempt += 1) {
        try {
          const next = await getSettings();
          onSettingsChanged(next);
          message(success + (kind === "tavily" && action === "save" ? " Режим поиска не изменён." : ""));
          return;
        } catch {
          if (attempt < 19) await new Promise(resolve => setTimeout(resolve, 500));
        }
      }
      message(`${success} Ядро ещё запускается. Статус обновится после подключения.`);
    } catch {
      message(action === "check" ? "Не удалось проверить подключение. Попробуйте ещё раз."
        : action === "save" ? "Не удалось сохранить ключ. Проверьте подключение к Iris."
          : "Не удалось удалить ключ. Проверьте подключение к Iris.", true);
    } finally {
      busyRef.current = false;
      setBusy(null);
    }
  };

  return <>
    {!desktop && <div className="notice" role="status">Управление ключами доступно в установленном приложении Iris.</div>}
    {(["deepseek", "coding", "tavily", "brave", "serper"] as Credential[]).filter(kind =>
      kind !== "brave" && kind !== "serper" || configured(kind)).map(kind => {
      const detail = DETAILS[kind];
      const legacy = kind === "brave" || kind === "serper";
      const hasKey = configured(kind);
      const result = messages[kind];
      return <section className="settings-card settings-credential-card" key={kind} aria-labelledby={`credential-${kind}`}>
        <div className="settings-card-header">
          <div className="settings-card-header-main"><div className="settings-card-title-group">
            <h3 className="settings-card-title settings-target-heading" id={`credential-${kind}`} tabIndex={-1}>{detail.title}</h3>
            <p className="settings-card-subtitle">{detail.description}</p>
          </div></div>
          <div className="settings-card-header-actions">
            <span className={`settings-status-pill ${hasKey ? "is-active" : kind === "deepseek" ? "is-warning" : ""}`}>
              <span className="settings-status-dot" aria-hidden="true" />{hasKey ? "Ключ настроен" : "Ключ не настроен"}
            </span>
          </div>
        </div>
        {!legacy && <label htmlFor={`${kind}-api-key-input`}>
          <input id={`${kind}-api-key-input`} type="password" autoComplete="new-password"
            aria-label={detail.label}
            value={inputs[kind] ?? ""} disabled={Boolean(busy) || !desktop}
            onChange={event => setInputs(current => ({ ...current, [kind]: event.target.value }))}
            placeholder={hasKey ? "Введите новый ключ для замены" : "Введите API-ключ"} />
        </label>}
        <div className="settings-card-actions">
          {!legacy && <MaterialButton materialKey={`credentials.${kind}.save`} type="button" className="primary-button"
            disabled={Boolean(busy) || !desktop || !inputs[kind]?.trim()} onClick={() => void act(kind, "save")}>
            {hasKey ? "Заменить ключ" : "Сохранить ключ"}
          </MaterialButton>}
          {!legacy && <MaterialButton materialKey={`credentials.${kind}.portal`} type="button" className="secondary"
            onClick={() => void openPortal(kind as CredentialTarget)}>
            Получить API-ключ<ExternalLink size={15} aria-hidden="true" />
          </MaterialButton>}
          {hasKey && <MaterialButton materialKey={`credentials.${kind}.remove`} type="button" className="danger-button"
            disabled={Boolean(busy) || !desktop} onClick={() => void act(kind, "remove")}>Удалить</MaterialButton>}
          {kind === "tavily" && hasKey && <MaterialButton materialKey="credentials.tavily.check" type="button" className="secondary"
            title="Проверка расходует поисковый кредит." disabled={Boolean(busy) || !hasKey}
            onClick={() => void act(kind, "check")}>Проверить подключение</MaterialButton>}
        </div>
        {busy === kind && <p role="status">Выполняем…</p>}
        {result && <p className={result.error ? "settings-action-error" : "settings-credential-hint"}
          role={result.error ? "alert" : "status"}>{result.text}</p>}
      </section>;
    })}
  </>;
}
