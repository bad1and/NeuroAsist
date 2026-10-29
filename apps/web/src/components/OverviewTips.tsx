import { useLayoutEffect, useRef, useState } from "react";
import { IconInterfaceArrowUpRight, IconInterfaceChevronLeft, IconInterfaceChevronRight } from "../CustomIcons";
import { animate, isTestEnvironment, prefersReducedMotion } from "../animations";
import type { SettingsSection } from "../settings/registry";
import { MaterialButton } from "./MaterialButton";

type TipAction = { label: string } & (
  | { view: "settings"; section: SettingsSection; focusId?: string }
  | { view: "memory" }
);
type OverviewTip = {
  id: string;
  title: string;
  description: string;
  action?: TipAction;
};

const tips: OverviewTip[] = [
  {
    id: "voice",
    title: "Пусть Iris звучит по-вашему",
    description: "Темп и выразительность голоса можно настроить под себя.",
    action: { label: "Настроить голос", view: "settings", section: "voice" },
  },
  {
    id: "memory",
    title: "Память можно поправить",
    description: "Исправляйте неточности в воспоминаниях и удаляйте лишнее.",
    action: { label: "Посмотреть память", view: "memory" },
  },
  {
    id: "shortcuts",
    title: "Частые действия — под рукой",
    description: "Микрофон, поиск и звук — одним сочетанием клавиш.",
    action: { label: "Выбрать сочетания", view: "settings", section: "shortcuts" },
  },
  {
    id: "pronunciation",
    title: "Сложное имя — знакомое звучание",
    description: "Добавьте имена и термины в словарь, чтобы Iris произносила их правильно.",
    action: { label: "Открыть словарь", view: "settings", section: "voice", focusId: "voice-pronunciations" },
  },
  {
    id: "incognito",
    title: "Не каждый разговор нужно запоминать",
    description: "В режиме инкогнито новые сообщения и факты не сохраняются.",
    action: { label: "Перейти к инкогнито", view: "settings", section: "memory", focusId: "memory-incognito" },
  },
  {
    id: "search",
    title: "Свежие факты лучше проверять",
    description: "Подключите поиск, чтобы Iris проверяла свежую информацию по источникам.",
    action: { label: "Настроить поиск", view: "settings", section: "internet" },
  },
  {
    id: "backups",
    title: "У важных разговоров может быть копия",
    description: "Сохраните историю, память и настройки перед переездом на другой компьютер.",
    action: { label: "Открыть резервные копии", view: "settings", section: "backups" },
  },
  {
    id: "team",
    title: "Интересный факт",
    description: "Данный проект разрабатывает полтора разработчика.",
  },
];

export function OverviewTips({ onOpenSettings, onOpenMemory }: {
  onOpenSettings?: (section: SettingsSection, focusId?: string) => void;
  onOpenMemory: () => void;
}) {
  const [index, setIndex] = useState(0);
  const contentRef = useRef<HTMLDivElement>(null);
  const directionRef = useRef(1);
  const previousIndex = useRef(index);
  const tip = tips[index];
  const action = tip.action;
  const canOpen = action && (action.view === "memory" || onOpenSettings);

  const select = (next: number) => {
    directionRef.current = next < index ? -1 : 1;
    setIndex((next + tips.length) % tips.length);
  };

  useLayoutEffect(() => {
    if (previousIndex.current === index) return;
    previousIndex.current = index;
    if (!contentRef.current || isTestEnvironment()) return;
    const reduced = prefersReducedMotion();
    const motion = animate(contentRef.current, {
      opacity: [0, 1],
      translateX: reduced ? 0 : [directionRef.current * 8, 0],
      duration: reduced ? 100 : 200,
      ease: "outQuad",
    });
    return () => { motion.revert(); };
  }, [index]);

  return <section className="overview-surface overview-tips overview-reveal" aria-label="Больше об Iris" aria-roledescription="карусель">
    <header className="overview-tips-header">
      <h2 className="overview-tips-heading">Больше об Iris</h2>
      <div className="overview-tips-controls" role="group" aria-label="Перелистывание советов" onKeyDown={event => {
        if (event.altKey || event.ctrlKey || event.metaKey) return;
        if (event.key === "ArrowLeft") { event.preventDefault(); select(index - 1); }
        else if (event.key === "ArrowRight") { event.preventDefault(); select(index + 1); }
        else if (event.key === "Home") { event.preventDefault(); select(0); }
        else if (event.key === "End") { event.preventDefault(); select(tips.length - 1); }
      }}>
        <MaterialButton materialKey="overview.tips.previous" type="button" className="icon-button" aria-label="Предыдущий совет" aria-controls="overview-tip-content" onClick={() => select(index - 1)}>
          <IconInterfaceChevronLeft size={19} aria-hidden="true" />
        </MaterialButton>
        <MaterialButton materialKey="overview.tips.next" type="button" className="icon-button" aria-label="Следующий совет" aria-controls="overview-tip-content" onClick={() => select(index + 1)}>
          <IconInterfaceChevronRight size={19} aria-hidden="true" />
        </MaterialButton>
      </div>
    </header>
    <div className="overview-tip-illustration" aria-hidden="true"><img src="/brand/iris-mark-dark.svg" alt="" draggable={false} /></div>
    <div id="overview-tip-content" className="overview-tip" ref={contentRef}>
      <div className="overview-tip-copy" aria-live="polite" aria-atomic="true">
        <h3>{tip.title}</h3>
        <p className="overview-tip-description">{tip.description}</p>
        <span className="overview-tip-position">Совет {index + 1} из {tips.length}</span>
      </div>
      {canOpen && <MaterialButton key={tip.id} materialKey={`overview.tips.${tip.id}`} type="button" className="secondary-button overview-tip-action" onClick={() => {
        if (action.view === "memory") onOpenMemory();
        else onOpenSettings?.(action.section, action.focusId);
      }}>
        <span>{action.label}</span><IconInterfaceArrowUpRight size={17} aria-hidden="true" />
      </MaterialButton>}
    </div>
  </section>;
}
