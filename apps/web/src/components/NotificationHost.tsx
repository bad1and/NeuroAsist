import React, { useState, useEffect, useRef, useCallback } from "react";
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Info,
  Bell,
  ChevronDown,
  ChevronUp,
  X,
  Layers,
} from "lucide-react";
import { useNotifications, notify, type AppNotification, type NotificationType } from "../notifications";
import { animateButtonPress } from "../animations";

interface NotificationHostProps {
  onNavigate?: (view: string) => void;
}

function getIcon(type: NotificationType) {
  switch (type) {
    case "error":
      return <AlertCircle size={18} aria-hidden="true" />;
    case "warning":
      return <AlertTriangle size={18} aria-hidden="true" />;
    case "success":
      return <CheckCircle2 size={18} aria-hidden="true" />;
    case "reminder":
      return <Bell size={18} aria-hidden="true" />;
    case "info":
    default:
      return <Info size={18} aria-hidden="true" />;
  }
}

export function NotificationHost({ onNavigate }: NotificationHostProps) {
  const notifications = useNotifications();
  const [isExpanded, setIsExpanded] = useState(false);
  const [isExiting, setIsExiting] = useState(false);
  const [isPaused, setIsPaused] = useState(false);
  const exitingTimerRef = useRef<number | null>(null);

  const active: AppNotification | undefined = notifications[0];
  const remainingCount = Math.max(0, notifications.length - 1);

  // Reset expanded state when active notification changes
  useEffect(() => {
    setIsExpanded(false);
    setIsExiting(false);
  }, [active?.id]);

  const handleDismiss = useCallback(
    (id?: string) => {
      const targetId = id ?? active?.id;
      if (!targetId || isExiting) return;

      setIsExiting(true);
      if (exitingTimerRef.current !== null) {
        window.clearTimeout(exitingTimerRef.current);
      }
      exitingTimerRef.current = window.setTimeout(() => {
        notify.dismiss(targetId);
        setIsExiting(false);
      }, 190);
    },
    [active?.id, isExiting]
  );

  // Smart auto-dismiss timer
  useEffect(() => {
    if (!active || active.duration === "persistent" || isPaused || isExiting) {
      return;
    }

    const duration = active.duration ?? 4500;
    const timer = window.setTimeout(() => {
      handleDismiss(active.id);
    }, duration);

    return () => {
      window.clearTimeout(timer);
    };
  }, [active, isPaused, isExiting, handleDismiss]);

  if (!active) {
    return null;
  }

  const isAutoDismiss = active.duration !== "persistent" && typeof active.duration === "number";
  const hasDetails = Boolean(active.details);
  const isLongMessage = (active.message?.length ?? 0) > 100 || active.message?.includes("\n");
  const canExpand = hasDetails || isLongMessage;

  const handleCardClick = (e: React.MouseEvent<HTMLDivElement>) => {
    // If user clicked inside a button, don't trigger full card click
    const target = e.target as HTMLElement;
    if (target.closest("button") || target.closest("a")) {
      return;
    }

    if (active.navigateView && onNavigate) {
      onNavigate(active.navigateView);
      handleDismiss(active.id);
    }
  };

  return (
    <aside
      className="notification-host"
      aria-label="Уведомления приложения"
      aria-live="polite"
    >
      {remainingCount > 0 && (
        <div className="notification-stack-layers" aria-hidden="true">
          {remainingCount > 1 && <div className="notification-card-stack-layer layer-2" />}
          <div className="notification-card-stack-layer layer-1" />
        </div>
      )}

      <div
        className={`notification-card notification-type-${active.type}${
          isExiting ? " is-exiting" : ""
        }${isExpanded ? " is-expanded" : ""}${active.navigateView ? " is-clickable" : ""}`}
        onMouseEnter={() => setIsPaused(true)}
        onMouseLeave={() => setIsPaused(false)}
        onClick={handleCardClick}
        role={active.type === "error" ? "alert" : "status"}
      >
        <div className="notification-card-header">
          <div className="notification-icon-box">{getIcon(active.type)}</div>

          <div className="notification-header-content">
            <div className="notification-title-row">
              <strong className="notification-title">{active.title}</strong>
              {remainingCount > 0 && (
                <button
                  type="button"
                  className="notification-stack-badge"
                  title="Остальные уведомления в очереди"
                  onClick={(e) => {
                    e.stopPropagation();
                    animateButtonPress(e.currentTarget);
                    handleDismiss(active.id);
                  }}
                >
                  <Layers size={11} aria-hidden="true" />
                  <span>+{remainingCount}</span>
                </button>
              )}
            </div>

            <p className={`notification-message${isExpanded ? " is-expanded" : ""}`}>
              {active.message}
            </p>
          </div>

          <div className="notification-controls">
            {canExpand && (
              <button
                type="button"
                className="icon-button notification-control-btn"
                aria-label={isExpanded ? "Свернуть подробности" : "Развернуть подробности"}
                title={isExpanded ? "Свернуть" : "Развернуть"}
                onClick={(e) => {
                  e.stopPropagation();
                  animateButtonPress(e.currentTarget);
                  setIsExpanded(!isExpanded);
                }}
              >
                {isExpanded ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
              </button>
            )}

            <button
              type="button"
              className="icon-button notification-control-btn notification-close-btn"
              aria-label="Закрыть уведомление"
              title="Закрыть"
              onClick={(e) => {
                e.stopPropagation();
                animateButtonPress(e.currentTarget);
                handleDismiss(active.id);
              }}
            >
              <X size={15} />
            </button>
          </div>
        </div>

        {isExpanded && active.details && (
          <div className="notification-details-wrapper">
            <pre className="notification-details">{active.details}</pre>
          </div>
        )}

        {active.actions && active.actions.length > 0 && (
          <div className="notification-actions">
            {active.actions.map((action, idx) => (
              <button
                key={idx}
                type="button"
                className={`notification-action-btn${
                  action.variant === "primary" ? " is-primary" : " is-secondary"
                }`}
                onClick={(e) => {
                  e.stopPropagation();
                  animateButtonPress(e.currentTarget);
                  action.onClick();
                  handleDismiss(active.id);
                }}
              >
                {action.label}
              </button>
            ))}
          </div>
        )}

        {isAutoDismiss && (
          <div
            className={`notification-progress-bar${isPaused ? " is-paused" : ""}`}
            style={{ animationDuration: `${active.duration}ms` }}
          />
        )}
      </div>
    </aside>
  );
}
