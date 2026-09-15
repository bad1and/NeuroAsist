import { useEffect, useState, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { IconInterfaceCross, IconInterfaceAlertTriangle } from "../CustomIcons";
import { animateButtonPress } from "../animations";

export interface AppDialogProps {
  open: boolean;
  title: string;
  description?: string;
  children?: ReactNode;
  onClose: () => void;
  icon?: ReactNode;
  variant?: "warning" | "danger" | "info";
}

export function AppDialog({
  open,
  title,
  description,
  children,
  onClose,
  icon,
  variant = "warning",
}: AppDialogProps) {
  const [isExiting, setIsExiting] = useState(false);
  const [rendered, setRendered] = useState(open);
  const exitTimerRef = useRef<number | null>(null);

  const cachedContentRef = useRef({
    title,
    description,
    children,
    icon,
    variant,
  });

  if (open) {
    cachedContentRef.current = { title, description, children, icon, variant };
  }

  useEffect(() => {
    return () => {
      if (exitTimerRef.current !== null) {
        window.clearTimeout(exitTimerRef.current);
      }
    };
  }, []);

  const prevOpenRef = useRef(open);

  useEffect(() => {
    if (prevOpenRef.current && !open && rendered && !isExiting) {
      // open переключился с true на false (например, по нажатию Отмена)
      setIsExiting(true);
      exitTimerRef.current = window.setTimeout(() => {
        setRendered(false);
        setIsExiting(false);
      }, 190);
    } else if (!prevOpenRef.current && open) {
      // open переключился с false на true (диалог открылся)
      setIsExiting(false);
      setRendered(true);
      if (exitTimerRef.current !== null) {
        window.clearTimeout(exitTimerRef.current);
        exitTimerRef.current = null;
      }
    }
    prevOpenRef.current = open;
  }, [open, rendered, isExiting]);

  useEffect(() => {
    if (!open) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [open, onClose]);

  if (!rendered || typeof document === "undefined") {
    return null;
  }

  const handleDismiss = () => {
    if (isExiting) return;
    setIsExiting(true);
    if (exitTimerRef.current !== null) {
      window.clearTimeout(exitTimerRef.current);
    }
    exitTimerRef.current = window.setTimeout(() => {
      setRendered(false);
      setIsExiting(false);
      onClose();
    }, 190);
  };

  const handleBodyClick = (e: React.MouseEvent) => {
    const target = e.target as HTMLElement;
    const secondaryBtn = target.closest("button.secondary");
    if (secondaryBtn) {
      animateButtonPress(secondaryBtn as HTMLElement);
    }
  };

  const currentTitle = open ? title : cachedContentRef.current.title;
  const currentDescription = open ? description : cachedContentRef.current.description;
  const currentChildren = open ? children : cachedContentRef.current.children;
  const currentIcon = open ? icon : cachedContentRef.current.icon;
  const currentVariant = open ? variant : cachedContentRef.current.variant;

  const content = (
    <aside className="app-dialog-host" aria-label="Диалог подтверждения" aria-live="assertive">
      <div
        className={`notification-card app-dialog-card is-${currentVariant}${isExiting ? " is-exiting" : ""}`}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="app-dialog-title"
        aria-describedby={currentDescription ? "app-dialog-desc" : undefined}
      >
        <div className="notification-card-header">
          <div className="notification-icon-box">
            {currentIcon ?? <IconInterfaceAlertTriangle size={24} aria-hidden="true" />}
          </div>

          <div className="notification-header-content">
            <div className="notification-title-row">
              <h2 id="app-dialog-title" className="notification-title">
                {currentTitle}
              </h2>
            </div>

            {currentDescription && (
              <p id="app-dialog-desc" className="notification-message is-dialog-message">
                {currentDescription}
              </p>
            )}
          </div>

          <div className="notification-side-actions">
            <button
              type="button"
              className="notification-control-btn notification-close-btn"
              aria-label="Закрыть диалог"
              title="Закрыть"
              onClick={(e) => {
                e.stopPropagation();
                animateButtonPress(e.currentTarget);
                handleDismiss();
              }}
            >
              <IconInterfaceCross size={16} aria-hidden="true" />
            </button>
          </div>
        </div>

        {currentChildren && (
          <div className="notification-dialog-body" onClick={handleBodyClick}>
            {currentChildren}
          </div>
        )}
      </div>
    </aside>
  );

  return createPortal(content, document.body);
}
