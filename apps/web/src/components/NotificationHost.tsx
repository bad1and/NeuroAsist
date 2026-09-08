import React, { useState, useEffect, useRef, useCallback } from "react";
import {
  IconInterfaceCross,
  IconInterfaceCheckCircle,
  IconInterfaceAlertTriangle,
  IconInterfaceAlertCircle,
  IconInterfaceInfoCircle,
  IconInterfaceAlertAlarmBell2,
  IconInterfaceCopy,
  IconInterfaceChevronDown,
  IconInterfaceChevronUp,
  IconInterfaceFilesFolderCopy2,
} from "../CustomIcons";
import { useNotifications, notify, type AppNotification, type NotificationType } from "../notifications";
import { animateButtonPress } from "../animations";

interface NotificationHostProps {
  onNavigate?: (view: string) => void;
  maxVisible?: number;
}

function getIcon(type: NotificationType) {
  switch (type) {
    case "error":
      return <IconInterfaceAlertCircle size={24} aria-hidden="true" />;
    case "warning":
      return <IconInterfaceAlertTriangle size={24} aria-hidden="true" />;
    case "success":
      return <IconInterfaceCheckCircle size={24} aria-hidden="true" />;
    case "reminder":
      return <IconInterfaceAlertAlarmBell2 size={24} aria-hidden="true" />;
    case "info":
    default:
      return <IconInterfaceInfoCircle size={24} aria-hidden="true" />;
  }
}

interface NotificationCardProps {
  notification: AppNotification;
  onNavigate?: (view: string) => void;
  onDismiss: (id: string) => void;
  remainingCount?: number;
}

function NotificationCard({
  notification,
  onNavigate,
  onDismiss,
  remainingCount = 0,
}: NotificationCardProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [isExiting, setIsExiting] = useState(false);
  const [isPaused, setIsPaused] = useState(false);
  const [copied, setCopied] = useState(false);
  const exitingTimerRef = useRef<number | null>(null);

  const handleDismiss = useCallback(() => {
    if (isExiting) return;
    setIsExiting(true);
    if (exitingTimerRef.current !== null) {
      window.clearTimeout(exitingTimerRef.current);
    }
    exitingTimerRef.current = window.setTimeout(() => {
      onDismiss(notification.id);
    }, 190);
  }, [notification.id, isExiting, onDismiss]);

  useEffect(() => {
    return () => {
      if (exitingTimerRef.current !== null) {
        window.clearTimeout(exitingTimerRef.current);
      }
    };
  }, []);

  // Smart auto-dismiss timer
  useEffect(() => {
    if (notification.duration === "persistent" || isPaused || isExiting) {
      return;
    }

    const duration = notification.duration ?? 4500;
    const timer = window.setTimeout(() => {
      handleDismiss();
    }, duration);

    return () => {
      window.clearTimeout(timer);
    };
  }, [notification.duration, isPaused, isExiting, handleDismiss]);

  const isAutoDismiss = notification.duration !== "persistent" && typeof notification.duration === "number";
  const hasDetails = Boolean(notification.details);
  const isLongMessage = (notification.message?.length ?? 0) > 90 || notification.message?.includes("\n");
  const canExpand = hasDetails || isLongMessage;
  const isError = notification.type === "error";
  const canCopy = hasDetails || isError;

  const handleCopy = (e: React.MouseEvent) => {
    e.stopPropagation();
    const textToCopy = notification.details
      ? `${notification.title}\n${notification.message}\n\n${notification.details}`
      : `${notification.title}: ${notification.message}`;
    void navigator.clipboard?.writeText(textToCopy);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  };

  const handleCardClick = (e: React.MouseEvent<HTMLDivElement>) => {
    const target = e.target as HTMLElement;
    if (target.closest("button") || target.closest("a") || target.closest("pre")) {
      return;
    }

    if (notification.navigateView && onNavigate) {
      onNavigate(notification.navigateView);
      handleDismiss();
    }
  };

  return (
    <div
      className={`notification-card notification-type-${notification.type}${
        isExiting ? " is-exiting" : ""
      }${isExpanded ? " is-expanded" : ""}${notification.navigateView ? " is-clickable" : ""}`}
      onMouseEnter={() => setIsPaused(true)}
      onMouseLeave={() => setIsPaused(false)}
      onClick={handleCardClick}
      role={notification.type === "error" ? "alert" : "status"}
    >
      <div className="notification-card-header">
        <div className="notification-icon-box">{getIcon(notification.type)}</div>

        <div className="notification-header-content">
          <div className="notification-title-row">
            <strong className="notification-title">{notification.title}</strong>
            {remainingCount > 0 && (
              <button
                type="button"
                className="notification-stack-badge"
                title="Остальные уведомления в очереди"
                onClick={(e) => {
                  e.stopPropagation();
                  animateButtonPress(e.currentTarget);
                  notify.dismissAll();
                }}
              >
                <IconInterfaceFilesFolderCopy2 size={11} aria-hidden="true" />
                <span>+{remainingCount}</span>
              </button>
            )}
          </div>

          <p className={`notification-message${isExpanded ? " is-expanded" : ""}`}>
            {notification.message}
          </p>

          {canExpand && (
            <button
              type="button"
              className="notification-expand-link"
              aria-label={isExpanded ? "Свернуть подробности" : "Развернуть подробности"}
              title={isExpanded ? "Свернуть подробности" : "Развернуть подробности"}
              onClick={(e) => {
                e.stopPropagation();
                animateButtonPress(e.currentTarget);
                setIsExpanded(!isExpanded);
              }}
            >
              <span>{isExpanded ? "Свернуть" : "Подробнее"}</span>
              {isExpanded ? (
                <IconInterfaceChevronUp size={10} aria-hidden="true" />
              ) : (
                <IconInterfaceChevronDown size={10} aria-hidden="true" />
              )}
            </button>
          )}
        </div>

        <div className="notification-side-actions">
          {notification.actions && notification.actions.length > 0 ? (
            notification.actions.map((action, idx) => (
              <button
                key={idx}
                type="button"
                className={`notification-action-btn notification-pill-btn${
                  action.variant === "primary" ? " is-primary" : " is-secondary"
                }`}
                onClick={(e) => {
                  e.stopPropagation();
                  animateButtonPress(e.currentTarget);
                  action.onClick();
                  handleDismiss();
                }}
              >
                {action.label}
              </button>
            ))
          ) : canCopy && isError ? (
            <button
              type="button"
              className={`notification-copy-btn${copied ? " is-copied" : ""}`}
              aria-label={copied ? "Скопировано!" : "Скопировать"}
              title={copied ? "Скопировано в буфер!" : "Скопировать ошибку"}
              onClick={(e) => {
                animateButtonPress(e.currentTarget);
                handleCopy(e);
              }}
            >
              {copied ? (
                <IconInterfaceCheckCircle size={15} aria-hidden="true" />
              ) : (
                <IconInterfaceCopy size={15} aria-hidden="true" />
              )}
              <span className="sr-only">{copied ? "Скопировано!" : "Скопировать"}</span>
            </button>
          ) : null}

          <button
            type="button"
            className="notification-control-btn notification-close-btn"
            aria-label="Закрыть уведомление"
            title="Закрыть"
            onClick={(e) => {
              e.stopPropagation();
              handleDismiss();
            }}
          >
            <IconInterfaceCross size={16} aria-hidden="true" />
          </button>
        </div>
      </div>

      {isExpanded && notification.details && (
        <div className="notification-details-wrapper">
          <div className="notification-details-header">
            <span className="notification-details-label">Лог / Подробности</span>
            <button
              type="button"
              className={`notification-details-copy-btn${copied ? " is-copied" : ""}`}
              aria-label={copied ? "Скопировано!" : "Скопировать лог"}
              title={copied ? "Скопировано в буфер!" : "Скопировать лог"}
              onClick={(e) => {
                animateButtonPress(e.currentTarget);
                handleCopy(e);
              }}
            >
              {copied ? (
                <IconInterfaceCheckCircle size={13} aria-hidden="true" />
              ) : (
                <IconInterfaceCopy size={13} aria-hidden="true" />
              )}
              <span className="sr-only">{copied ? "Скопировано!" : "Скопировать лог"}</span>
            </button>
          </div>
          <pre className="notification-details">{notification.details}</pre>
        </div>
      )}

      {isAutoDismiss && (
        <div
          className={`notification-progress-bar${isPaused ? " is-paused" : ""}`}
          style={{ animationDuration: `${notification.duration}ms` }}
        />
      )}
    </div>
  );
}

export function NotificationHost({ onNavigate, maxVisible = 3 }: NotificationHostProps) {
  const notifications = useNotifications();

  if (notifications.length === 0) {
    return null;
  }

  const visibleNotifications = notifications.slice(0, maxVisible);
  const totalRemaining = Math.max(0, notifications.length - maxVisible);

  return (
    <aside
      className="notification-host"
      aria-label="Уведомления приложения"
      aria-live="polite"
    >
      {visibleNotifications.map((notif, index) => (
        <NotificationCard
          key={notif.id}
          notification={notif}
          onNavigate={onNavigate}
          onDismiss={notify.dismiss}
          remainingCount={index === 0 ? totalRemaining : 0}
        />
      ))}
    </aside>
  );
}
