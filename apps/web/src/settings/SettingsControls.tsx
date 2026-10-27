import { IconInterfaceLock } from "../CustomIcons";
import { interfaceIntlLocale } from "../i18n";
export function formatTime(value: string): string { const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleTimeString(interfaceIntlLocale(), { hour: "2-digit", minute: "2-digit" }); }
export function DevBadge({
  active,
  onClick,
  title,
}: {
  active?: boolean;
  onClick?: () => void;
  title?: string;
}) {
  return (
    <span
      className={`dev-badge${active ? " is-active" : ""}`}
      title={
        title ??
        (active
          ? "Параметр режима разработчика"
          : "Требуется режим разработчика (нажмите, чтобы перейти в раздел «Для разработчиков»)")
      }
      onClick={(e) => {
        if (onClick) {
          e.preventDefault();
          e.stopPropagation();
          onClick();
        }
      }}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={(e) => {
        if (onClick && (e.key === "Enter" || e.key === " ")) {
          e.preventDefault();
          onClick();
        }
      }}
    >
      <IconInterfaceLock size={10} aria-hidden="true" />
      <span>Dev</span>
    </span>
  );
}


