import { MaterialButton } from "./MaterialButton";
import { useEffect, useId, useLayoutEffect, useState, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { IconInterfaceCross, IconInterfaceAlertTriangle } from "../CustomIcons";
import { animateButtonPress, animateNotification } from "../animations";
import { ConfirmationRim } from "./ConfirmationRim";
import { buttonSeed } from "./buttonMaterial";

export interface AppDialogProps {
  open: boolean;
  title: string;
  description?: string;
  children?: ReactNode;
  onClose: () => void;
  icon?: ReactNode;
  variant?: "warning" | "danger" | "info";
  size?: "compact" | "wide";
}

export function AppDialog({
  open,
  title,
  description,
  children,
  onClose,
  icon,
  variant = "warning",
  size = "compact",
}: AppDialogProps) {
  const [isExiting, setIsExiting] = useState(false);
  const [rendered, setRendered] = useState(open);
  const exitTimerRef = useRef<number | null>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  const openerRef = useRef<HTMLElement | null>(null);
  const titleId = useId();
  const descriptionId = useId();
  useLayoutEffect(() => {
    if (open) {
      const active = document.activeElement;
      if (!openerRef.current && active instanceof HTMLElement && !cardRef.current?.contains(active)) openerRef.current = active;
      if (rendered && cardRef.current && !cardRef.current.contains(active)) {
        (cardRef.current.querySelector<HTMLElement>("[autofocus], input:not([disabled]), button:not([disabled]), [tabindex='0']") || cardRef.current).focus();
      }
    } else if (openerRef.current) {
      const active = document.activeElement;
      if (active === document.body || cardRef.current?.contains(active)) {
        if (openerRef.current.isConnected) openerRef.current.focus();
      }
      openerRef.current = null;
    }
  }, [open, rendered]);
  useLayoutEffect(() => {
    if (!rendered || !cardRef.current) return;
    const motion = animateNotification(cardRef.current, isExiting ? "exit" : "enter");
    return () => { motion?.cancel(); };
  }, [rendered, isExiting]);

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
      const dialogs = document.querySelectorAll(".app-dialog-card:not(.is-exiting)");
      if (dialogs[dialogs.length - 1] !== cardRef.current) return;
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
      if (e.key === "Tab" && cardRef.current) {
        const controls = [...cardRef.current.querySelectorAll<HTMLElement>("button:not([disabled]), input:not([disabled]):not([type='hidden']), select:not([disabled]), textarea:not([disabled]), a[href], summary, [tabindex='0']")].filter(element => !element.closest("[hidden], [inert]") && !element.closest("details:not([open]) > :not(summary)"));
        const first = controls[0], last = controls[controls.length - 1];
        if (!first) { e.preventDefault(); cardRef.current.focus(); }
        else if (e.shiftKey && (document.activeElement === first || !cardRef.current.contains(document.activeElement))) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && (document.activeElement === last || !cardRef.current.contains(document.activeElement))) { e.preventDefault(); first.focus(); }
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
    <aside className={`app-dialog-host${size === "wide" ? " is-wide" : ""}`} aria-label={currentVariant === "info" ? "Диалог" : "Диалог подтверждения"} aria-live={currentVariant === "info" ? "off" : "assertive"}>
      <div
        ref={cardRef}
        className={`notification-card app-dialog-card confirmation-surface is-${currentVariant}${size === "wide" ? " is-wide" : ""}${isExiting ? " is-exiting" : ""}`}
        role={currentVariant === "info" ? "dialog" : "alertdialog"}
        tabIndex={-1}
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={currentDescription ? descriptionId : undefined}
      >
        <div className="notification-card-header">
          <div className="notification-icon-box">
            {currentIcon ?? <IconInterfaceAlertTriangle size={24} aria-hidden="true" />}
          </div>

          <div className="notification-header-content">
            <div className="notification-title-row">
              <h2 id={titleId} className="notification-title">
                {currentTitle}
              </h2>
            </div>

            {currentDescription && (
              <p id={descriptionId} className="notification-message is-dialog-message">
                {currentDescription}
              </p>
            )}
          </div>

          <div className="notification-side-actions">
            <MaterialButton materialKey={"dialog.close." + title}
              appearance="quiet"
              type="button"
              className="notification-control-btn notification-close-btn confirmation-close"
              aria-label="Закрыть диалог"
              title="Закрыть"
              onClick={(e) => {
                e.stopPropagation();
                animateButtonPress(e.currentTarget);
                handleDismiss();
              }}
            >
              <IconInterfaceCross size={16} aria-hidden="true" />
            </MaterialButton>
          </div>
        </div>

        {currentChildren && (
          <div className="notification-dialog-body" onClick={handleBodyClick}>
            {currentChildren}
          </div>
        )}
        <ConfirmationRim cardRef={cardRef} seed={buttonSeed(`confirmation.${currentTitle}`)} active={open && !isExiting} />
      </div>
    </aside>
  );

  return createPortal(content, document.body);
}
