import { useState, useRef, useEffect } from "react";
import { createPortal } from "react-dom";
import { Zap, Copy, Check, X, ChevronDown, ChevronRight, Terminal } from "lucide-react";
import type { TokenMetadata } from "../types";

export function formatTokens(count?: number): string {
  if (count === undefined || count === null || isNaN(count)) return "0";
  if (count >= 1_000_000) return `${(count / 1_000_000).toFixed(1)}M`;
  if (count >= 1_000) return `${(count / 1_000).toFixed(1)}k`;
  return count.toLocaleString().replace(/\u00a0/g, " ");
}

export function calculateCostUsd(tokens: TokenMetadata): number {
  const hit = tokens.prompt_cache_hit_tokens ?? 0;
  const miss = tokens.prompt_cache_miss_tokens ?? (tokens.prompt_tokens ?? 0);
  const completion = tokens.completion_tokens ?? 0;
  // DeepSeek standard pricing: $0.07/M cached, $0.27/M uncached, $1.10/M completion
  const cost = (hit * 0.00000007) + (miss * 0.00000027) + (completion * 0.0000011);
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

  const isUser = role === "user";
  const promptTokens = tokens?.prompt_tokens ?? 0;
  const completionTokens = tokens?.completion_tokens ?? 0;
  const totalTokens = tokens?.total_tokens ?? (promptTokens + completionTokens);

  const handleCopyJson = async () => {
    const rawData = tokens.raw_usage || tokens;
    try {
      await navigator.clipboard.writeText(JSON.stringify(rawData, null, 2));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback
    }
  };

  const cost = calculateCostUsd(tokens);
  const cacheHit = tokens.prompt_cache_hit_tokens ?? 0;
  const cacheMiss = tokens.prompt_cache_miss_tokens ?? 0;
  const cacheTotal = cacheHit + cacheMiss;
  const cacheHitPercent = cacheTotal > 0 ? Math.round((cacheHit / cacheTotal) * 100) : null;

  return (
    <div className="app-dialog-body token-dialog-body">
      <div className="token-popover-grid">
        {/* Input Tokens */}
        <div className="token-metric-card">
          <span className="token-metric-label">Входящие (Prompt)</span>
          <span className="token-metric-value text-prompt">
            {promptTokens > 0 ? promptTokens.toLocaleString() : (tokens.prompt_tokens?.toLocaleString() ?? "—")}
          </span>
          {cacheTotal > 0 && (
            <div className="token-submetric">
              <span className="cache-tag hit">Hit: {cacheHit.toLocaleString()}</span>
              <span className="cache-tag miss">Miss: {cacheMiss.toLocaleString()}</span>
              {cacheHitPercent !== null && (
                <span className="cache-rate">({cacheHitPercent}%)</span>
              )}
            </div>
          )}
        </div>

        {/* Output Tokens */}
        <div className="token-metric-card">
          <span className="token-metric-label">Исходящие (Output)</span>
          <span className="token-metric-value text-completion">
            {completionTokens > 0 ? completionTokens.toLocaleString() : (isUser ? "—" : tokens.completion_tokens?.toLocaleString() ?? "—")}
          </span>
          {(tokens.reasoning_tokens ?? 0) > 0 && (
            <div className="token-submetric">
              <span className="reasoning-tag">
                Мысли: {tokens.reasoning_tokens?.toLocaleString()}
              </span>
            </div>
          )}
        </div>

        {/* Total Tokens */}
        <div className="token-metric-card">
          <span className="token-metric-label">Всего токенов</span>
          <span className="token-metric-value text-total">
            {totalTokens.toLocaleString()}
          </span>
          {tokens.latency_ms !== undefined && tokens.latency_ms > 0 && (
            <div className="token-submetric">
              <span>Задержка: {tokens.latency_ms} мс</span>
            </div>
          )}
        </div>

        {/* Estimated Cost */}
        <div className="token-metric-card">
          <span className="token-metric-label">Стоимость (DeepSeek)</span>
          <span className="token-metric-value text-cost">
            {cost > 0 ? `$${cost < 0.0001 ? "<0.0001" : cost.toFixed(5)}` : "—"}
          </span>
          <div className="token-submetric">
            <span>Ориентировочно</span>
          </div>
        </div>
      </div>

      {/* Raw JSON toggle */}
      <div className="token-raw-section">
        <button
          type="button"
          className="token-raw-toggle-btn"
          onClick={() => setShowRawJson((prev) => !prev)}
        >
          <div className="token-raw-toggle-label">
            <Terminal size={12} />
            <span>Сырой JSON ответа</span>
          </div>
          {showRawJson ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </button>

        {showRawJson && (
          <div className="token-raw-content">
            <div className="token-raw-actions">
              <button
                type="button"
                className="token-copy-btn secondary"
                onClick={handleCopyJson}
                title="Скопировать сырой JSON"
              >
                {copied ? <Check size={12} /> : <Copy size={12} />}
                <span>{copied ? "Скопировано!" : "Копировать"}</span>
              </button>
            </div>
            <pre className="token-json-viewer">
              <code>
                {JSON.stringify(tokens.raw_usage || tokens, null, 2)}
              </code>
            </pre>
          </div>
        )}
      </div>

      <div className="dialog-actions" style={{ marginTop: "14px", display: "flex", justifyContent: "flex-end" }}>
        <button
          type="button"
          className="secondary"
          onClick={onClose}
        >
          Понятно
        </button>
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
      <button
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
      </button>

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
                  <button
                    type="button"
                    className="notification-control-btn notification-close-btn"
                    onClick={() => setInternalOpen(false)}
                    aria-label="Закрыть"
                    title="Закрыть диалог"
                  >
                    <X size={18} aria-hidden="true" />
                  </button>
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
