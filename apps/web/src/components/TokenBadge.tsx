import { useState, useRef, useEffect, useCallback } from "react";
import { createPortal } from "react-dom";
import { Zap, Copy, Check, X, ChevronDown, ChevronRight, Terminal } from "lucide-react";
import type { TokenMetadata } from "../types";

interface TokenBadgeProps {
  tokens?: TokenMetadata | null;
  role: "user" | "assistant" | "system_event";
}

function formatTokens(count?: number): string {
  if (count === undefined || count === null || isNaN(count)) return "0";
  if (count >= 1_000_000) return `${(count / 1_000_000).toFixed(1)}M`;
  if (count >= 1_000) return `${(count / 1_000).toFixed(1)}k`;
  return count.toLocaleString().replace(/\u00a0/g, " ");
}

function calculateCostUsd(tokens: TokenMetadata): number {
  const hit = tokens.prompt_cache_hit_tokens ?? 0;
  const miss = tokens.prompt_cache_miss_tokens ?? (tokens.prompt_tokens ?? 0);
  const completion = tokens.completion_tokens ?? 0;
  // DeepSeek standard pricing: $0.07/M cached, $0.27/M uncached, $1.10/M completion
  const cost = (hit * 0.00000007) + (miss * 0.00000027) + (completion * 0.0000011);
  return Math.round(cost * 1_000_000) / 1_000_000;
}

export function TokenBadge({ tokens, role }: TokenBadgeProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [showRawJson, setShowRawJson] = useState(false);
  const [copied, setCopied] = useState(false);
  const [popoverPos, setPopoverPos] = useState<{ top: number; left: number } | null>(null);

  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const popoverRef = useRef<HTMLDivElement | null>(null);

  const isUser = role === "user";
  const promptTokens = tokens?.prompt_tokens ?? 0;
  const completionTokens = tokens?.completion_tokens ?? 0;
  const totalTokens = tokens?.total_tokens ?? (promptTokens + completionTokens);

  if (!tokens || (promptTokens === 0 && completionTokens === 0 && totalTokens === 0)) {
    return null;
  }

  const updatePosition = useCallback(() => {
    if (!buttonRef.current) return;
    const rect = buttonRef.current.getBoundingClientRect();
    const popoverWidth = 340;
    const popoverHeight = 360;

    let left = rect.left;
    if (rect.right + popoverWidth > window.innerWidth - 16) {
      left = Math.max(16, rect.right - popoverWidth);
    }

    let top = rect.bottom + 6;
    if (top + popoverHeight > window.innerHeight - 16) {
      top = Math.max(16, rect.top - popoverHeight - 6);
    }

    setPopoverPos({ top, left });
  }, []);

  const handleToggle = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!isOpen) {
      updatePosition();
      setIsOpen(true);
    } else {
      setIsOpen(false);
    }
  };

  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setIsOpen(false);
      }
    };

    const handleClickOutside = (e: MouseEvent) => {
      if (
        popoverRef.current &&
        !popoverRef.current.contains(e.target as Node) &&
        buttonRef.current &&
        !buttonRef.current.contains(e.target as Node)
      ) {
        setIsOpen(false);
      }
    };

    const handleScroll = () => {
      updatePosition();
    };

    document.addEventListener("keydown", handleKeyDown);
    document.addEventListener("mousedown", handleClickOutside);
    window.addEventListener("scroll", handleScroll, true);
    window.addEventListener("resize", handleScroll);

    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.removeEventListener("mousedown", handleClickOutside);
      window.removeEventListener("scroll", handleScroll, true);
      window.removeEventListener("resize", handleScroll);
    };
  }, [isOpen, updatePosition]);

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

  const badgeText = isUser
    ? `${formatTokens(promptTokens)} in`
    : `${formatTokens(completionTokens || totalTokens)} out`;

  const cost = calculateCostUsd(tokens);
  const cacheHit = tokens.prompt_cache_hit_tokens ?? 0;
  const cacheMiss = tokens.prompt_cache_miss_tokens ?? 0;
  const cacheTotal = cacheHit + cacheMiss;
  const cacheHitPercent = cacheTotal > 0 ? Math.round((cacheHit / cacheTotal) * 100) : null;

  return (
    <div className="token-badge-container">
      <button
        ref={buttonRef}
        type="button"
        className={`token-badge ${isUser ? "user-badge" : "assistant-badge"} ${isOpen ? "active" : ""}`}
        onClick={handleToggle}
        title="Нажмите для полной детализации токенов"
        aria-label={`Токены: ${badgeText}. Нажмите для детализации`}
        aria-expanded={isOpen}
      >
        <Zap size={11} className="token-badge-icon" />
        <span className="token-badge-text">{badgeText}</span>
      </button>

      {isOpen &&
        popoverPos &&
        createPortal(
          <div
            ref={popoverRef}
            className="token-popover-portal"
            style={{
              top: `${popoverPos.top}px`,
              left: `${popoverPos.left}px`,
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="token-popover-header">
              <div className="token-popover-title-row">
                <Zap size={14} className="token-accent-icon" />
                <span className="token-popover-title">Статистика токенов</span>
                {tokens.model && (
                  <span className="token-model-chip" title={`Модель: ${tokens.model}`}>
                    {tokens.model}
                  </span>
                )}
              </div>
              <button
                type="button"
                className="token-popover-close-btn"
                onClick={() => setIsOpen(false)}
                aria-label="Закрыть"
              >
                <X size={14} />
              </button>
            </div>

            <div className="token-popover-grid">
              {/* Input Tokens */}
              <div className="token-metric-card">
                <span className="token-metric-label">Входящие (Prompt)</span>
                <span className="token-metric-value text-prompt">
                  {tokens.prompt_tokens?.toLocaleString() ?? "—"}
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
                  {tokens.completion_tokens?.toLocaleString() ?? "—"}
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
                      className="token-copy-btn"
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
          </div>,
          document.body
        )}
    </div>
  );
}
