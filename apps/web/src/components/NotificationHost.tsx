import { MaterialButton } from "./MaterialButton";
import React, { useState, useLayoutEffect, useRef, useCallback } from "react";
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
import { animateButtonPress, animateNotification, NOTIFICATION_EXIT_DURATION } from "../animations";
import { buttonSeed } from "./buttonMaterial";
import { NotificationCountdown, NotificationTaskProgress, useNotificationCountdown } from "./NotificationCountdown";
import { useNotificationDialogOffset } from "./useNotificationDialogOffset";
import "./NotificationHost.css";

interface NotificationHostProps {
  pinnedContentRef?: React.RefObject<HTMLDivElement | null>;
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

export function NotificationCard({
  notification,
  onNavigate,
  onDismiss,
  remainingCount = 0,
}: NotificationCardProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [isExiting, setIsExiting] = useState(false);
  const [isHovered, setIsHovered] = useState(false);
  const [isFocused, setIsFocused] = useState(false);
  const [copied, setCopied] = useState(false);
  const exitingTimerRef = useRef<number | null>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  const countdownRef = useRef<SVGPathElement>(null);
  const seed = buttonSeed(`notification.${notification.id}`);
  const taskProgress = notification.progress === undefined
    ? null : Math.min(1, Math.max(0, notification.progress));
  const taskRunning = taskProgress !== null && taskProgress < 1;
  const duration = notification.duration === "persistent" || taskRunning ? null : notification.duration ?? 4500;
  const isPaused = isHovered || isFocused || isExpanded || isExiting;

  const handleDismiss = useCallback(() => {
    if (isExiting) return;
    setIsExiting(true);
    // The effect plays the same exit used by the pinned conversation card.
  }, [isExiting]);

  useLayoutEffect(() => {
    if (!cardRef.current) return;
    const motion = animateNotification(cardRef.current, isExiting ? "exit" : "enter", () => {
      if (isExiting) onDismiss(notification.id);
    });
    if (isExiting && !motion) {
      exitingTimerRef.current = window.setTimeout(() => onDismiss(notification.id), NOTIFICATION_EXIT_DURATION);
    }
    return () => {
      motion?.cancel();
      if (exitingTimerRef.current !== null) window.clearTimeout(exitingTimerRef.current);
    };
  }, [isExiting, notification.id, onDismiss]);

  useNotificationCountdown({ duration, paused: isPaused, onComplete: handleDismiss, pathRef: countdownRef });
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
      ref={cardRef}
      className={`notification-card notification-type-${notification.type}${
        isExiting ? " is-exiting" : ""
      }${isExpanded ? " is-expanded" : ""}${notification.navigateView ? " is-clickable" : ""}${taskProgress !== null && duration === null ? " has-task-progress" : ""}`}
      data-countdown-paused={duration !== null ? isPaused : undefined}
      data-material-seed={seed}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      onFocus={() => setIsFocused(true)}
      onBlur={(event) => {
        if (!(event.relatedTarget instanceof Node) || !event.currentTarget.contains(event.relatedTarget)) setIsFocused(false);
      }}
      onClick={handleCardClick}
      role={notification.type === "error" ? "alert" : "status"}
    >
      <div className="notification-card-header">
        <div className="notification-icon-box">{getIcon(notification.type)}</div>

        <div className="notification-header-content">
          <div className="notification-title-row">
            <strong className="notification-title">{notification.title}</strong>
            {remainingCount > 0 && (
              <MaterialButton materialKey={"NotificationHost.button-1." + notification.id}
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
              </MaterialButton>
            )}
          </div>

          <p className={`notification-message${isExpanded ? " is-expanded" : ""}`}>
            {notification.message}
          </p>

          {canExpand && (
            <MaterialButton materialKey={"NotificationHost.button-2." + notification.id}
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
            </MaterialButton>
          )}
        </div>

        <div className="notification-side-actions">
          {canCopy && isError && !notification.actions?.length ? (
            <MaterialButton materialKey={"NotificationHost.button-4." + notification.id}
              appearance="quiet"
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
            </MaterialButton>
          ) : null}

          <MaterialButton materialKey={"NotificationHost.button-5." + notification.id}
            appearance="quiet"
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
          </MaterialButton>
        </div>
      </div>

      {Boolean(notification.actions?.length) && <div className="notification-footer-actions">
        {notification.actions!.map((action, index) => <MaterialButton key={index}
          materialKey={`notification.${notification.id}.action.${index}`} type="button"
          className={`notification-action-btn notification-pill-btn ${action.variant === "primary" ? "is-primary" : "is-secondary"}`}
          onClick={(event) => {
            event.stopPropagation(); animateButtonPress(event.currentTarget); action.onClick(); handleDismiss();
          }}>{action.label}</MaterialButton>)}
      </div>}

      {isExpanded && notification.details && (
        <div className="notification-details-wrapper">
          <div className="notification-details-header">
            <span className="notification-details-label">Лог / Подробности</span>
            <MaterialButton materialKey={"NotificationHost.button-6." + notification.id}
              appearance="quiet"
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
            </MaterialButton>
          </div>
          <pre className="notification-details">{notification.details}</pre>
        </div>
      )}

      {taskProgress !== null && duration === null && <NotificationTaskProgress progress={taskProgress} />}
      {duration !== null && <NotificationCountdown cardRef={cardRef} pathRef={countdownRef} seed={seed} />}
    </div>
  );
}

export function NotificationHost({ onNavigate, maxVisible = 3, pinnedContentRef }: NotificationHostProps) {
  const notifications = useNotifications();
  const hostRef = useRef<HTMLElement>(null);
  const mounted = notifications.length > 0 || Boolean(pinnedContentRef);
  useNotificationDialogOffset(hostRef, mounted);

  if (!mounted) {
    return null;
  }

  const visibleNotifications = notifications.slice(0, maxVisible);
  const totalRemaining = Math.max(0, notifications.length - maxVisible);

  return (
    <aside
      ref={hostRef}
      className="notification-host"
      aria-label="Уведомления приложения"
      aria-live="polite"
    >
      {visibleNotifications.length > 0 && (
        <div key="notifications" className="notification-stack">
          {visibleNotifications.map((notif, index) => (
            <NotificationCard
              key={notif.id}
              notification={notif}
              onNavigate={onNavigate}
              onDismiss={notify.dismiss}
              remainingCount={index === 0 ? totalRemaining : 0}
            />
          ))}
        </div>
      )}
      {pinnedContentRef && <div key="pinned-conversation" ref={pinnedContentRef} className="notification-pinned-slot" />}
    </aside>
  );
}
