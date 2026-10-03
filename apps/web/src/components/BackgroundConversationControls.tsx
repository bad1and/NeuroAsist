import { MaterialButton } from "./MaterialButton";
import { FigmaMicIcon, FigmaHeadphonesIcon, FigmaExitIcon } from "../FigmaIcons";
import { animateButtonPress } from "../animations";

export function BackgroundConversationControls({
  microphoneActive, microphoneStarting, microphoneDisabled, soundMuted,
  onMicrophone, onSound, onMinimize,
}: {
  microphoneActive: boolean;
  microphoneStarting: boolean;
  microphoneDisabled: boolean;
  soundMuted: boolean;
  onMicrophone: () => void;
  onSound: () => void;
  onMinimize: () => void;
}) {
  const microphoneLabel = microphoneActive ? "Выключить микрофон" : "Включить микрофон";
  const soundLabel = soundMuted ? "Включить звук" : "Выключить звук";
  return (
    <div className="background-conversation-controls">
      <div className="background-conversation-actions">
        <MaterialButton materialKey={"BackgroundConversationControls.button-1"} type="button" className={`notification-pill-btn conversation-control ${microphoneActive ? "is-primary" : "is-secondary"}`} aria-label={microphoneLabel} title={microphoneLabel} disabled={microphoneDisabled} aria-busy={microphoneStarting} aria-pressed={microphoneActive} onClick={(e) => { animateButtonPress(e.currentTarget); onMicrophone(); }}>
          <FigmaMicIcon width={18} height={20} aria-hidden="true" />
        </MaterialButton>
        <MaterialButton materialKey={"BackgroundConversationControls.button-2"} type="button" className="notification-pill-btn is-secondary conversation-control" aria-label={soundLabel} title={soundLabel} aria-pressed={!soundMuted} onClick={(e) => { animateButtonPress(e.currentTarget); onSound(); }}>
          <FigmaHeadphonesIcon width={20} height={19} aria-hidden="true" />
        </MaterialButton>
        <MaterialButton materialKey={"BackgroundConversationControls.button-3"} type="button" className="notification-pill-btn is-secondary conversation-control" aria-label="Свернуть панель разговора" title="Свернуть панель разговора" onClick={(e) => { animateButtonPress(e.currentTarget); onMinimize(); }}>
          <FigmaExitIcon width={20} height={20} aria-hidden="true" />
        </MaterialButton>
      </div>
    </div>
  );
}

export function BackgroundConversationExpandButton({ onExpand }: { onExpand: () => void }) {
  return <MaterialButton materialKey={"BackgroundConversationControls.button-4"} appearance="plain" type="button" className="notification-pill-btn is-secondary conversation-control conversation-expand" aria-label="Развернуть панель разговора" title="Развернуть панель разговора" onClick={(e) => { animateButtonPress(e.currentTarget); onExpand(); }}>
    <FigmaExitIcon width={20} height={20} aria-hidden="true" />
  </MaterialButton>;
}
