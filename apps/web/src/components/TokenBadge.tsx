import { MaterialButton } from "./MaterialButton";
import { useState, useRef, useEffect, useId } from "react";
import { createPortal } from "react-dom";
import {
  IconInterfaceLightning as Zap,
  IconInterfaceCopy as Copy,
  IconInterfaceCheck as Check,
  IconInterfaceCross as X,
  IconInterfaceChevronDown as ChevronDown,
  IconInterfaceChevronRight as ChevronRight,
  IconInterfaceTerminal as Terminal,
  IconInterfaceClock as Clock3,
} from "../CustomIcons";
import type { TokenMetadata } from "../types";
import { calculateDeepSeekCostUsd } from "../deepseek";
import { interfaceIntlLocale } from "../i18n";

export function formatTokens(count?: number): string {
  if (count === undefined || count === null || isNaN(count)) return "0";
  if (count >= 1_000_000) return `${(count / 1_000_000).toFixed(1)}M`;
  if (count >= 1_000) return `${(count / 1_000).toFixed(1)}k`;
  return count.toLocaleString().replace(/\u00a0/g, " ");
}

export function calculateCostUsd(tokens: TokenMetadata): number {
  const cost = calculateDeepSeekCostUsd(tokens);
  return Math.round(cost * 1_000_000) / 1_000_000;
}

export interface TokenDialogContentProps {
  tokens: TokenMetadata;
  role: "user" | "assistant" | "system_event";
  onClose: () => void;
}

export function TokenDialogContent({ tokens, role, onClose }: TokenDialogContentProps) {
  const [showRawJson, setShowRawJson] = useState(false);
  const [copied, setCopied] = useState(false);
  const rawJsonId = useId();
  const copyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (copyTimerRef.current !== null) clearTimeout(copyTimerRef.current);
  }, []);

  const isUser = role === "user";
  const promptTokens = tokens.prompt_tokens;
  const completionTokens = tokens.completion_tokens;
  const totalTokens = tokens.total_tokens ?? (
    promptTokens !== undefined && completionTokens !== undefined ? promptTokens + completionTokens
      : isUser ? promptTokens : undefined
  );
  const formatCount = (value?: number) => value !== undefined && Number.isFinite(value)
    ? value.toLocaleString(interfaceIntlLocale()) : "—";

  const handleCopyJson = async () => {
    const rawData = tokens.raw_usage || tokens;
    try {
      await navigator.clipboard.writeText(JSON.stringify(rawData, null, 2));
      setCopied(true);
      if (copyTimerRef.current !== null) clearTimeout(copyTimerRef.current);
      copyTimerRef.current = setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback
    }
  };

  const cost = calculateCostUsd(tokens);
  const cacheHit = tokens.prompt_cache_hit_tokens;
  const cacheMiss = tokens.prompt_cache_miss_tokens;
  const hasCache = cacheHit !== undefined || cacheMiss !== undefined;
  const cacheTotal = promptTokens ?? (cacheHit !== undefined && cacheMiss !== undefined ? cacheHit + cacheMiss : 0);
  const cacheHitPercent = cacheHit !== undefined && cacheTotal > 0 && cacheHit >= 0 && cacheHit <= cacheTotal
    ? Math.round((cacheHit / cacheTotal) * 100) : null;

  return (
    <div className="app-dialog-body token-dialog-body">
      <div className="token-popover-grid">
        {/* Input Tokens */}
        <div className="token-metric-card">
          <span className="token-metric-label">На входе</span>
          <span className="token-metric-value" data-i18n-skip>
            {formatCount(promptTokens)}
          </span>
        </div>

        {/* Output Tokens */}
        <div className="token-metric-card">
          <span className="token-metric-label">В ответе</span>
          <span className="token-metric-value" data-i18n-skip>
            {formatCount(completionTokens)}
          </span>
          {(tokens.reasoning_tokens ?? 0) > 0 && (
            <div className="token-submetric">
              <span>Рассуждения: <span data-i18n-skip>{formatCount(tokens.reasoning_tokens)}</span></span>
            </div>
          )}
        </div>

        {/* Total Tokens */}
        <div className="token-metric-card">
          <span className="token-metric-label">Всего токенов</span>
          <span className="token-metric-value" data-i18n-skip>
            {formatCount(totalTokens)}
          </span>
        </div>

        {/* Estimated Cost */}
        <div className="token-metric-card">
          <span className="token-metric-label">Оценка стоимости</span>
          <span className="token-metric-value token-cost-value" data-i18n-skip>
            {cost > 0 ? cost < 0.0001 ? "< $0.0001" : `$${cost.toFixed(5)}` : "—"}
          </span>
        </div>
      </div>

      {hasCache && (
        <section className="token-cache-section" aria-label="Кэш запроса">
          <div className="token-cache-heading"><span>Кэш запроса</span>{cacheHitPercent !== null && <span data-i18n-skip>{cacheHitPercent}%</span>}</div>
          {cacheHitPercent !== null && <div className="token-cache-meter" aria-hidden="true"><span style={{ width: `${cacheHitPercent}%` }} /></div>}
          <dl className="token-cache-breakdown">
            <div><dt>Из кэша</dt><dd data-i18n-skip>{formatCount(cacheHit)}</dd></div>
            <div><dt>Без кэша</dt><dd data-i18n-skip>{formatCount(cacheMiss)}</dd></div>
          </dl>
        </section>
      )}

      {tokens.latency_ms !== undefined && tokens.latency_ms >= 0 && (
        <div className="token-response-time"><span><Clock3 size={14} aria-hidden="true" />Время ответа</span><span data-i18n-skip>{new Intl.NumberFormat(interfaceIntlLocale(), { maximumFractionDigits: 2 }).format(tokens.latency_ms / 1000)} {interfaceIntlLocale() === "en-US" ? "s" : "с"}</span></div>
      )}

      {/* Raw JSON toggle */}
      <div className="token-raw-section">
        <MaterialButton materialKey={"TokenBadge.button-1"}
          type="button"
          className="secondary token-raw-toggle-btn"
          aria-expanded={showRawJson}
          aria-controls={rawJsonId}
          onClick={() => setShowRawJson((prev) => !prev)}
        >
          <span className="token-raw-toggle-label">
            <Terminal size={15} aria-hidden="true" />
            <span>JSON ответа</span>
          </span>
          <ChevronDown size={15} aria-hidden="true" />
        </MaterialButton>

        <div id={rawJsonId} className="token-raw-content" hidden={!showRawJson}>
          {showRawJson && <>
            <div className="token-raw-actions">
              <MaterialButton materialKey={"TokenBadge.button-2"}
                type="button"
                className="token-copy-btn secondary"
                onClick={handleCopyJson}
                title="Скопировать сырой JSON"
              >
                {copied ? <Check size={14} aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />}
                <span>{copied ? "Скопировано!" : "Копировать"}</span>
              </MaterialButton>
            </div>
            <pre className="token-json-viewer" data-i18n-skip tabIndex={0}>
              <code>
                {JSON.stringify(tokens.raw_usage || tokens, null, 2)}
              </code>
            </pre>
          </>}
        </div>
      </div>

      <div className="dialog-actions token-dialog-actions">
        <MaterialButton materialKey={"TokenBadge.button-3"}
          type="button"
          className="secondary"
          onClick={onClose}
        >
          Понятно
        </MaterialButton>
      </div>
    </div>
  );
}

export interface TokenBadgeProps {
  tokens?: TokenMetadata | null;
  role: "user" | "assistant" | "system_event";
  onOpen?: () => void;
}

export function TokenBadge({ tokens, role, onOpen }: TokenBadgeProps) {
  const [internalOpen, setInternalOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const popoverRef = useRef<HTMLDivElement | null>(null);

  const isUser = role === "user";
  const promptTokens = tokens?.prompt_tokens ?? 0;
  const completionTokens = tokens?.completion_tokens ?? 0;
  const totalTokens = tokens?.total_tokens ?? (promptTokens + completionTokens);

  if (!tokens || (promptTokens === 0 && completionTokens === 0 && totalTokens === 0)) {
    return null;
  }

  const handleToggle = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (onOpen) {
      onOpen();
    } else {
      setInternalOpen((prev) => !prev);
    }
  };

  useEffect(() => {
    if (!internalOpen) return;

    const handleClickOutside = (e: MouseEvent) => {
      const target = e.target as HTMLElement | null;
      if (!target) return;
      if (popoverRef.current?.contains(target)) return;
      if (buttonRef.current?.contains(target)) return;
      if (target.closest?.(".token-dialog-card") || target.closest?.(".token-badge")) return;
      setInternalOpen(false);
    };

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setInternalOpen(false);
      }
    };

    const timer = window.setTimeout(() => {
      document.addEventListener("mousedown", handleClickOutside);
    }, 20);
    document.addEventListener("keydown", handleKeyDown);

    return () => {
      window.clearTimeout(timer);
      document.removeEventListener("mousedown", handleClickOutside);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [internalOpen]);

  const badgeText = isUser
    ? `${formatTokens(promptTokens)} in`
    : `${formatTokens(completionTokens || totalTokens)} out`;

  return (
    <div className="token-badge-container">
      <MaterialButton materialKey={"TokenBadge.button-4"}
        ref={buttonRef}
        type="button"
        className={`token-badge ${isUser ? "user-badge" : "assistant-badge"} ${internalOpen ? "active" : ""}`}
        onClick={handleToggle}
        title="Нажмите для полной детализации токенов"
        aria-label={`Токены: ${badgeText}. Нажмите для детализации`}
        aria-expanded={internalOpen}
      >
        <Zap size={11} className="token-badge-icon" />
        <span className="token-badge-text">{badgeText}</span>
      </MaterialButton>

      {internalOpen &&
        createPortal(
          <aside
            className="app-dialog-host token-dialog-host"
            aria-label="Статистика токенов"
            aria-live="assertive"
          >
            <div
              ref={popoverRef}
              className="notification-card app-dialog-card is-info token-dialog-card"
              role="alertdialog"
              aria-modal="true"
              aria-labelledby="token-dialog-title"
              aria-describedby="token-dialog-desc"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="notification-card-header">
                <div className="notification-icon-box">
                  <Zap size={22} aria-hidden="true" />
                </div>
                <div className="notification-header-content">
                  <div className="notification-title-row">
                    <h2 id="token-dialog-title" className="notification-title">
                      Статистика токенов
                    </h2>
                  </div>
                  <p id="token-dialog-desc" className="notification-message is-dialog-message">
                    {tokens.model ? tokens.model : "Детализация использования токенов"}
                  </p>
                </div>
                <div className="notification-side-actions">
                  <MaterialButton materialKey={"TokenBadge.button-5"}
                    type="button"
                    className="notification-control-btn notification-close-btn"
                    onClick={() => setInternalOpen(false)}
                    aria-label="Закрыть"
                    title="Закрыть диалог"
                  >
                    <X size={18} aria-hidden="true" />
                  </MaterialButton>
                </div>
              </div>

              <TokenDialogContent
                tokens={tokens}
                role={role}
                onClose={() => setInternalOpen(false)}
              />
            </div>
          </aside>,
          document.body
        )}
    </div>
  );
}
