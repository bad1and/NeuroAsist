import { useLayoutEffect, useRef, useState } from "react";
import { MaterialButton } from "../components/MaterialButton";
import { AppDialog } from "../components/AppDialog";
import { NavigationDisclosure } from "../components/NavigationDisclosure";
import { useScrollEdgeFade } from "../components/useScrollEdgeFade";
import {
  IconMailChatBubbleTextSquare, IconTravelMapEarth1, IconComputerDatabase,
  IconComputerScreenCurve, IconInterfaceKey, IconInterfaceActivity,
  IconInterfaceChevronDown, IconInterfaceBookOpen,
} from "../CustomIcons";
import { openChangelog } from "../changelog/notice";
import { SETTINGS_GROUPS, SETTINGS_SECTIONS, searchSettings, type SettingsSection, type SettingsPageId } from "./registry";

const icons: Record<string, typeof IconInterfaceKey> = {
  conversation: IconMailChatBubbleTextSquare, internet: IconTravelMapEarth1,
  data: IconComputerDatabase, application: IconComputerScreenCurve,
  connections: IconInterfaceKey, diagnostics: IconInterfaceActivity,
};

export function SettingsNavigation({ current, developerMode = false, onChange }: {
  current: SettingsPageId; developerMode?: boolean;
  onChange: (section: SettingsSection, focusId?: string) => void;
}) {
  const scrollRef = useRef<HTMLElement | null>(null);
  useScrollEdgeFade(scrollRef);
  const [query, setQuery] = useState("");
  const [pickerOpen, setPickerOpen] = useState(false);
  const activeGroup = SETTINGS_GROUPS.find(group => group.sections.includes(current))?.id;
  const [expandedGroup, setExpandedGroup] = useState<string | null>(activeGroup ?? null);
  useLayoutEffect(() => { setExpandedGroup(activeGroup ?? null); }, [current, activeGroup]);

  const choose = (section: SettingsPageId | "changelog", focusId?: string) => {
    setPickerOpen(false);
    setQuery("");
    if (section === "changelog") openChangelog();
    else {
      setExpandedGroup(SETTINGS_GROUPS.find(group => group.sections.includes(section))?.id ?? null);
      onChange(section, focusId);
    }
  };
  const sectionButton = (section: SettingsPageId) => (
    <MaterialButton key={section} materialKey={`settings.navigation.${section}`} type="button"
      className={`settings-nav-button${current === section ? " is-active" : ""}`}
      aria-current={current === section ? "page" : undefined} onClick={() => choose(section)}>
      <span>{SETTINGS_SECTIONS[section].title}</span>
    </MaterialButton>
  );
  const search = <input className="settings-search-field" type="search" value={query}
    aria-label="Поиск по настройкам" placeholder="Найти настройку" maxLength={120}
    onChange={event => setQuery(event.target.value)} />;
  const contents = (picker: boolean) => query.trim() ? (
    <div className="settings-search-results" role="region" aria-label="Результаты поиска настроек">
      {searchSettings(query, developerMode).map((item, index) => <MaterialButton
        key={`${item.section}-${item.focusId ?? index}`} materialKey={`settings.search.${item.section}.${item.focusId ?? "page"}`}
        aria-label={item.title} appearance="quiet" className="settings-search-result" onClick={() => choose(item.section, item.focusId)}>
        <span>{item.title}</span>
        {item.section !== "changelog" && item.focusId && <small>{SETTINGS_SECTIONS[item.section].title}</small>}
      </MaterialButton>)}
      {!searchSettings(query, developerMode).length && <p className="muted settings-search-empty">Ничего не найдено. Попробуйте другое название.</p>}
    </div>
  ) : <>
    {SETTINGS_GROUPS.map(group => {
      const Icon = icons[group.icon];
      const items = group.sections.filter(section => section !== "events" || developerMode);
      const open = picker || expandedGroup === group.id;
      const id = `settings-nav-${picker ? "picker" : "desktop"}-${group.id}`;
      return <div className={`settings-nav-group${group.id === activeGroup ? " is-active" : ""}`} key={group.id}>
        {picker ? <h3 className="settings-picker-group-title"><Icon size={18} aria-hidden="true" />{group.label}</h3> : <MaterialButton materialKey={`settings.group.${group.id}`} className="settings-nav-group-button"
          aria-expanded={open} aria-controls={id} onClick={() => setExpandedGroup(value => value === group.id ? null : group.id)}>
          <Icon size={20} aria-hidden="true" /><span>{group.label}</span><IconInterfaceChevronDown size={15} className="settings-nav-chevron" aria-hidden="true" />
        </MaterialButton>}
        <NavigationDisclosure id={id} open={open}>{items.map(section => sectionButton(section))}</NavigationDisclosure>
      </div>;
    })}
    <MaterialButton materialKey="settings.about" className={`settings-nav-direct${current === "about" ? " is-active" : ""}`}
      aria-current={current === "about" ? "page" : undefined} onClick={() => choose("about")}>
      <IconInterfaceBookOpen size={20} aria-hidden="true" /><span>О приложении</span>
    </MaterialButton>
  </>;

  return <>
    <div className="settings-navigation">
      <div className="settings-search">{search}</div>
      <nav className="settings-navigation-scroll" ref={scrollRef} aria-label="Разделы настроек">{contents(false)}</nav>
    </div>
    <div className="settings-navigation-compact">
      <MaterialButton materialKey="settings.open-picker" className="secondary settings-picker-button"
        aria-label={`Выбрать раздел настроек: ${SETTINGS_SECTIONS[current].title}`} aria-haspopup="dialog" onClick={() => setPickerOpen(true)}>
        <span>{SETTINGS_SECTIONS[current].title}</span><IconInterfaceChevronDown size={16} aria-hidden="true" />
      </MaterialButton>
    </div>
    <AppDialog open={pickerOpen} title="Разделы настроек" icon={<IconComputerScreenCurve size={20} aria-hidden="true" />} onClose={() => setPickerOpen(false)} variant="info" size="wide" className="settings-picker-dialog">
      <div className="settings-search">{search}</div>
      <nav aria-label="Выбор раздела настроек">{contents(true)}</nav>
    </AppDialog>
  </>;
}
