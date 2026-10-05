import type { CSSProperties } from "react";
import { ButtonMaterialLayers } from "./MaterialButton";
import { materialStyle } from "./buttonMaterial";
import "./MaterialButton.css";

const selectionStyle = {
  ...materialStyle(42, 0),
  "--lens-depth": "var(--depth-selection-active)",
} as CSSProperties;

/** Keep the approved button grain on the shared recessed field surface. */
export function SelectionMaterial({ tone = "accent" }:
  { tone?: "accent" | "graphite" | "thumb" }) {
  return <span className={`iris-selection-material dp-lens dp-${tone === "accent" ? "accent" : "graphite"}`}
    data-selection-tone={tone} style={selectionStyle} aria-hidden="true">
    <ButtonMaterialLayers />
  </span>;
}
