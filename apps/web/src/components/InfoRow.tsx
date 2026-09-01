import { type ReactNode } from "react";

export interface InfoRowProps {
  label: ReactNode;
  value: ReactNode;
  title?: string;
  className?: string;
}

export function InfoRow({ label, value, title, className = "" }: InfoRowProps) {
  const displayTitle = title ?? (typeof value === "string" ? value : undefined);
  return (
    <div className={`info-row ${className}`.trim()}>
      <span>{label}</span>
      <strong title={displayTitle}>{value}</strong>
    </div>
  );
}
