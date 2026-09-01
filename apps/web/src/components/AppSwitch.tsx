import { type ReactNode } from "react";

export interface AppSwitchProps {
  checked: boolean;
  label: ReactNode;
  description?: ReactNode;
  disabled?: boolean;
  className?: string;
  onChange: (checked: boolean) => void;
}

export function AppSwitch({
  checked,
  label,
  description,
  disabled,
  className = "",
  onChange,
}: AppSwitchProps) {
  return (
    <label className={`settings-switch-row ${className}${disabled ? " is-disabled" : ""}`.trim()}>
      <span className="settings-switch-copy">
        <strong>{label}</strong>
        {description && <small>{description}</small>}
      </span>
      <input
        className="settings-switch-input"
        type="checkbox"
        role="switch"
        aria-checked={checked}
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span className="settings-switch" aria-hidden="true">
        <span />
      </span>
    </label>
  );
}
