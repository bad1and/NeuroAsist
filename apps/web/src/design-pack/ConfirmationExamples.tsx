import { useRef, useState, type ReactNode } from "react";
import { MessageSquarePlus, X } from "lucide-react";
import { MaterialButton } from "../components/MaterialButton";
import { ConfirmationRim } from "../components/ConfirmationRim";
import { buttonSeed } from "../components/buttonMaterial";

function ConfirmationSample({ id, solidCancel, label, review }: { id: string; solidCancel?: boolean; label: string; review: ReactNode }) {
  const [result, setResult] = useState<string | null>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  const seed = buttonSeed(`confirmation.${id}`);
  return <section className="dp-confirmation-option" aria-labelledby={`${id}-variant`}>
    <div className="dp-confirmation-review"><h3 id={`${id}-variant`}>{label}</h3>{review}</div>
    <div className="dp-confirmation-stage">
      {result === null ? <div ref={cardRef} className="dp-confirmation-card confirmation-surface is-danger" role="group"
        aria-labelledby={`${id}-title`} aria-describedby={`${id}-description`}>
        <div className="dp-confirmation-header">
          <MessageSquarePlus className="dp-confirmation-icon" size={24} aria-hidden="true" />
          <div className="dp-confirmation-copy">
            <h2 id={`${id}-title`}>Начать новый диалог?</h2>
            <p id={`${id}-description`}>Текущий разговор сохраним в истории. После этого начнётся новый диалог с Iris.</p>
          </div>
          <MaterialButton materialKey={`${id}.close`} appearance="quiet" className="dp-confirmation-close confirmation-close"
            aria-label="Закрыть подтверждение" onClick={() => setResult("Окно закрыто.")}>
            <X size={16} aria-hidden="true" />
          </MaterialButton>
        </div>
        <div className="dp-confirmation-actions">
          <MaterialButton materialKey={`${id}.cancel`} appearance={solidCancel ? "lens" : "quiet"}
            className="dp-confirmation-action" onClick={() => setResult("Текущий диалог продолжается.")}>Отмена</MaterialButton>
          <MaterialButton materialKey={`${id}.new`} tone="danger" className="dp-confirmation-action"
            onClick={() => setResult("Новый диалог выбран.")}>Новый диалог</MaterialButton>
        </div>
        <ConfirmationRim cardRef={cardRef} seed={seed} />
      </div> : <div className="dp-confirmation-result">
        <p role="status">{result}</p>
        <MaterialButton materialKey={`${id}.restore`} appearance="quiet" onClick={() => setResult(null)}>Показать снова</MaterialButton>
      </div>}
    </div>
  </section>;
}

export function ConfirmationExamples({ renderReview }: { renderReview: (id: string) => ReactNode }) {
  return <section className="dp-section dp-confirmation-examples" aria-labelledby="confirmations-title">
    <div className="dp-section-heading"><h2 id="confirmations-title">Подтверждения</h2></div>
    <div className="dp-two-up">
      <ConfirmationSample id="confirmation-calm" label="Лёгкая отмена" review={renderReview("confirmation-calm")} />
      <ConfirmationSample id="confirmation-rim" label="Объёмная отмена" solidCancel review={renderReview("confirmation-rim")} />
    </div>
  </section>;
}
