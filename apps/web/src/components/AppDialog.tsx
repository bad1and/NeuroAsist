import { MaterialButton } from "./MaterialButton";
import { useEffect, useId, useLayoutEffect, useState, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { IconInterfaceCross, IconInterfaceAlertTriangle } from "../CustomIcons";
import { animate, animateButtonPress, animateNotification, isTestEnvironment, prefersReducedMotion } from "../animations";
import { ConfirmationRim } from "./ConfirmationRim";
import { buttonSeed } from "./buttonMaterial";

export interface AppDialogProps {
  open: boolean;
  title: string;
  description?: string;
  headerContent?: ReactNode;
  children?: ReactNode;
  onClose: () => void;
  icon?: ReactNode;
  variant?: "warning" | "danger" | "info";
  size?: "compact" | "wide";
  presentation?: "notification" | "spotlight";
}

export function AppDialog({
  open,
  title,
  description,
  headerContent,
  children,
  onClose,
  icon,
  variant = "warning",
  size = "compact",
  presentation = "notification",
}: AppDialogProps) {
  const [isExiting, setIsExiting] = useState(false);
  const [rendered, setRendered] = useState(open);
  const exitTimerRef = useRef<number | null>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  const headerRef = useRef<HTMLDivElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const hostRef = useRef<HTMLElement>(null);
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
    } else if (openerRef.current && (presentation !== "spotlight" || !rendered)) {
      const active = document.activeElement;
      if (active === document.body || cardRef.current?.contains(active)) {
        if (openerRef.current.isConnected) openerRef.current.focus();
      }
      openerRef.current = null;
    }
  }, [open, rendered, presentation]);
  useLayoutEffect(() => {
    if (!rendered || presentation !== "spotlight") return;
    const background = [...document.body.children].filter(element => element !== hostRef.current && element instanceof HTMLElement) as HTMLElement[];
    const previous = background.map(element => element.hasAttribute("inert"));
    background.forEach(element => element.setAttribute("inert", ""));
    return () => background.forEach((element, index) => { if (!previous[index]) element.removeAttribute("inert"); });
  }, [rendered, presentation]);
  useLayoutEffect(() => {
    if (!rendered || !cardRef.current) return;
    if (presentation === "spotlight") {
      if (isTestEnvironment()) return;
      const reduced = prefersReducedMotion();
      const motion = animate(cardRef.current, {
        opacity: isExiting ? [1, 0] : [0, 1],
        translateY: reduced ? 0 : isExiting ? [0, 8] : [12, 0],
        scale: reduced ? 1 : isExiting ? [1, .99] : [.98, 1],
        duration: isExiting ? 180 : 240,
        ease: "outCubic",
      });
      const backdropMotion = hostRef.current ? animate(hostRef.current, {
        opacity: isExiting ? [1, 0] : [0, 1],
        duration: reduced ? 100 : isExiting ? 180 : 240,
        ease: "outQuad",
      }) : null;
      return () => { motion.cancel(); backdropMotion?.cancel(); };
    }
    const motion = animateNotification(cardRef.current, isExiting ? "exit" : "enter");
    return () => { motion?.cancel(); };
  }, [rendered, isExiting, presentation]);

  const cachedContentRef = useRef({
    title,
    description,
    headerContent,
    children,
    icon,
    variant,
  });

  if (open) {
    cachedContentRef.current = { title, description, headerContent, children, icon, variant };
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
        if (presentation === "spotlight") handleDismiss();
        else onClose();
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
  }, [open, onClose, presentation, isExiting]);

  if (!rendered || typeof document === "undefined") {
    return null;
  }

  function handleDismiss() {
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
  }

  const handleBodyClick = (e: React.MouseEvent) => {
    const target = e.target as HTMLElement;
    const secondaryBtn = target.closest("button.secondary");
    if (secondaryBtn) {
      animateButtonPress(secondaryBtn as HTMLElement);
    }
  };

  const currentTitle = open ? title : cachedContentRef.current.title;
  const currentDescription = open ? description : cachedContentRef.current.description;
  const currentHeaderContent = open ? headerContent : cachedContentRef.current.headerContent;
  const currentChildren = open ? children : cachedContentRef.current.children;
  const currentIcon = open ? icon : cachedContentRef.current.icon;
  const currentVariant = open ? variant : cachedContentRef.current.variant;
  const detached = presentation === "spotlight" && Boolean(currentHeaderContent);

  const content = (
    <aside ref={hostRef} className={`app-dialog-host${size === "wide" ? " is-wide" : ""}${presentation === "spotlight" ? " is-spotlight" : ""}`} onMouseDown={presentation === "spotlight" ? event => { if (event.target === event.currentTarget && event.button === 0) handleDismiss(); } : undefined} aria-label={currentVariant === "info" ? "Диалог" : "Диалог подтверждения"} aria-live={currentVariant === "info" ? "off" : "assertive"}>
      <div
        ref={cardRef}
        className={`notification-card app-dialog-card confirmation-surface is-${currentVariant}${size === "wide" ? " is-wide" : ""}${detached ? " is-detached" : ""}${isExiting ? " is-exiting" : ""}`}
        role={currentVariant === "info" ? "dialog" : "alertdialog"}
        tabIndex={-1}
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={currentDescription ? descriptionId : undefined}
      >
        <div ref={headerRef} className={`notification-card-header${detached ? " spotlight-search-surface" : ""}`}>
          {!(presentation === "spotlight" && currentHeaderContent) && <div className="notification-icon-box">
            {currentIcon ?? <IconInterfaceAlertTriangle size={24} aria-hidden="true" />}
          </div>}

          <div className="notification-header-content">
            <div className="notification-title-row">
              <h2 id={titleId} className={currentHeaderContent ? "sr-only" : "notification-title"}>
                {currentTitle}
              </h2>
              {currentHeaderContent}
            </div>

            {currentDescription && (
              <p id={descriptionId} className="notification-message is-dialog-message">
                {currentDescription}
              </p>
            )}
          </div>

          <div className="notification-side-actions">
            <MaterialButton materialKey={"dialog.close." + title}
              appearance={presentation === "spotlight" ? "lens" : "quiet"}
              type="button"
              className={`notification-control-btn notification-close-btn confirmation-close${presentation === "spotlight" ? " icon-button" : ""}`}
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
          {detached && <ConfirmationRim cardRef={headerRef} seed={buttonSeed(`search-field.${currentTitle}`)} active={open && !isExiting} />}
        </div>

        {currentChildren && (
          <div ref={bodyRef} className={`notification-dialog-body${detached ? " spotlight-results-surface" : ""}`} onClick={handleBodyClick}>
            {currentChildren}
            {detached && <ConfirmationRim cardRef={bodyRef} seed={buttonSeed(`search-results.${currentTitle}`)} active={open && !isExiting} />}
          </div>
        )}
        {!detached && <ConfirmationRim cardRef={cardRef} seed={buttonSeed(`confirmation.${currentTitle}`)} active={open && !isExiting} />}
      </div>
    </aside>
  );

  return createPortal(content, document.body);
}
