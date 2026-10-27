import { MaterialButton } from "./MaterialButton";
import { Disclosure } from "./Disclosure";
import { useEffect, useId, useState, type ReactNode } from "react";
import type { PublicSettings } from "../types";

const profiles = [
  { label: "Спокойнее", engagement: "low", initiative: "off", description: "Реже вступает в беседу и не начинает её сама." },
  { label: "Обычно", engagement: "balanced", initiative: "rare", description: "Поддерживает разговор, изредка начинает сама." },
  { label: "Больше общения", engagement: "high", initiative: "balanced", description: "Чаще вступает в разговор и предлагает новые темы." },
] as const;

export function ConversationProfiles({ engagement, initiative, onChange, children }: { engagement: string; initiative: string; children?: ReactNode; onChange: (value: Pick<PublicSettings, "live_conversation_engagement" | "live_conversation_initiative">) => void }) {
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
    {children}
  </section>;
}

export function ConversationSettingsDetails({ hidden, children, reveal = false }: { hidden: boolean; children: ReactNode; reveal?: boolean }) {
  const [expanded, setExpanded] = useState(false);
  useEffect(() => { if (reveal) setExpanded(true); }, [reveal]);
  const isExpanded = expanded || reveal;
  return <Disclosure materialKey="conversation.all-settings" label="Настроить подробнее" className="conversation-settings-details"
    hidden={hidden} open={isExpanded} onOpenChange={setExpanded} contentClassName="conversation-settings-stack" regionLabel="Все параметры разговора">
    {children}
  </Disclosure>;
}
