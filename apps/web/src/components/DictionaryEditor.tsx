import { useId } from "react";
import { MaterialButton } from "./MaterialButton";

export function DictionaryEditor({ value, onChange, leftLabel, rightLabel, disabled = false }: {
  value: string; onChange: (value: string) => void; leftLabel: string; rightLabel: string; disabled?: boolean;
}) {
  const id = useId();
  const rows = value.split("\n").map(line => {
    const at = line.indexOf("=");
    return at < 0 ? [line, ""] : [line.slice(0, at).replace(/ $/, ""), line.slice(at + 1).replace(/^ /, "")];
  });
  const update = (index: number, column: number, next: string) => {
    const updated = rows.map((row, i) => i === index ? row.map((cell, n) => n === column ? next : cell) : row);
    onChange(updated.map(row => `${row[0]} = ${row[1]}`).join("\n"));
  };
  return <div className="dictionary-editor">
    {rows.map((row, index) => <div className="dictionary-row" key={index}>
      <label htmlFor={`${id}-${index}-left`}>{leftLabel}<input id={`${id}-${index}-left`} value={row[0]} disabled={disabled} onChange={event => update(index, 0, event.target.value)} /></label>
      <label htmlFor={`${id}-${index}-right`}>{rightLabel}<input id={`${id}-${index}-right`} value={row[1]} disabled={disabled} onChange={event => update(index, 1, event.target.value)} /></label>
      <MaterialButton materialKey={`dictionary.remove.${index}`} appearance="quiet" type="button" disabled={disabled} aria-label={`Удалить строку ${index + 1}`} onClick={() => onChange(rows.filter((_, n) => n !== index).map(cells => cells.join(" = ")).join("\n"))}>×</MaterialButton>
    </div>)}
    <MaterialButton materialKey="dictionary.add" className="secondary" type="button" disabled={disabled} onClick={() => onChange(value + (value ? "\n" : "") + " = ")}>Добавить слово</MaterialButton>
  </div>;
}
