import { MaterialButton } from "./MaterialButton";
import {
  IconInterfaceChevronDown as ChevronDown,
  IconInterfaceSliders as SlidersHorizontal,
} from "../CustomIcons";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { animate, prefersReducedMotion } from "../animations";
import type { PublicSettings } from "../types";

const profiles = [
  { label: "Спокойнее", engagement: "low", initiative: "off", description: "Сдержанное участие, без инициативных реплик." },
  { label: "Обычно", engagement: "balanced", initiative: "rare", description: "Сбалансированное участие и редкая инициатива." },
  { label: "Больше общения", engagement: "high", initiative: "balanced", description: "Больше участия и предложений продолжить беседу." },
] as const;

export function ConversationProfiles({ engagement, initiative, onChange }: { engagement: string; initiative: string; onChange: (value: Pick<PublicSettings, "live_conversation_engagement" | "live_conversation_initiative">) => void }) {
  const id = useId();
  const matched = profiles.some(profile => engagement === profile.engagement && initiative === profile.initiative);
  return <section className="settings-card conversation-profile-card">
    <div className="settings-card-header">
      <div className="settings-card-title-group">
        <h3 className="settings-card-title" id={`${id}-title`}>Участие в разговоре</h3>
        <p className="settings-card-subtitle">Выберите, насколько активно Iris участвует в беседе.</p>
      </div>
      {!matched && <span className="conversation-custom-profile">Свой вариант</span>}
    </div>
    <div className="conversation-profiles" role="group" aria-labelledby={`${id}-title`}>
      {profiles.map(profile => {
        const selected = engagement === profile.engagement && initiative === profile.initiative;
        return <MaterialButton materialKey={`conversation.profile.${profile.engagement}`} className="secondary conversation-profile" tone={selected ? "accent" : "graphite"} type="button" key={profile.label}
          aria-label={profile.label} aria-describedby={`${id}-${profile.engagement}`} aria-pressed={selected}
          onClick={() => onChange({ live_conversation_engagement: profile.engagement, live_conversation_initiative: profile.initiative })}>
          <span className="conversation-profile-copy">
            <span className="conversation-profile-heading"><strong>{profile.label}</strong></span>
            <small id={`${id}-${profile.engagement}`}>{profile.description}</small>
          </span>
        </MaterialButton>;
      })}
    </div>
  </section>;
}

export function ConversationSettingsDetails({ hidden, children }: { hidden: boolean; children: ReactNode }) {
  const [expanded, setExpanded] = useState(false);
  const id = useId();
  const content = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!expanded || !content.current || prefersReducedMotion()) return;
    const motion = animate(content.current, { opacity: [0, 1], translateY: [-4, 0], duration: 180, ease: "outQuad" });
    return () => { motion.revert(); };
  }, [expanded]);
  return <section className="conversation-settings-details" hidden={hidden}>
    <MaterialButton materialKey="conversation.all-settings" className="secondary conversation-settings-toggle" type="button" aria-expanded={expanded} aria-controls={id} onClick={() => setExpanded(value => !value)}>
      <SlidersHorizontal size={16} aria-hidden="true" />Все параметры разговора<ChevronDown size={16} aria-hidden="true" />
    </MaterialButton>
    <div id={id} className="conversation-settings-stack" ref={content} hidden={!expanded} role="region" aria-label="Все параметры разговора">{children}</div>
  </section>;
}
