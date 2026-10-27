import { useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  IconInterfaceArrowRight as ArrowRight,
  IconInterfaceBookOpen as BookOpen,
  IconInterfaceCheckCircle as CheckCircle,
  IconInterfaceClock as Clock,
  IconInterfaceInfoCircle as InfoCircle,
  IconInterfaceLayers as Layers,
  IconInterfaceSliders as Sliders,
  IconInterfaceSparkles as Sparkles,
} from "../CustomIcons";
import { animate, isTestEnvironment, prefersReducedMotion } from "../animations/core";
import { APP_VERSION, availableReleases, releaseDate } from "../changelog/catalog";
import { acknowledgeChangelog, CHANGELOG_NOTICE_ID, openChangelog, watchChangelogNotice } from "../changelog/notice";
import type { ReleaseImage, ReleaseNote } from "../changelog/types";
import { notify } from "../notifications";
import { AppDialog } from "./AppDialog";
import { CustomSelect } from "./CustomSelect";
import { MaterialButton } from "./MaterialButton";
import { useScrollEdgeFade } from "./useScrollEdgeFade";
import "./Changelog.css";

const sectionIcons = { new: Sparkles, improved: Sliders, fixed: CheckCircle };

function ReleaseFigure({ image }: { image: ReleaseImage }) {
  return <figure className="changelog-figure">
    <img src={image.src} alt={image.alt} width={image.width} height={image.height} loading="lazy" decoding="async" />
    {image.caption && <figcaption>{image.caption}</figcaption>}
  </figure>;
}

function ReleaseArticle({ release, installed }: { release: ReleaseNote; installed: boolean }) {
  const ref = useRef<HTMLElement>(null);
  useScrollEdgeFade(ref);
  useLayoutEffect(() => {
    if (!ref.current) return;
    ref.current.scrollTop = 0;
    if (isTestEnvironment()) return;
    const motion = animate(ref.current, { opacity: [0, 1], duration: prefersReducedMotion() ? 100 : 180, ease: "outQuad" });
    return () => { motion.cancel(); };
  }, [release.version]);
  return <article ref={ref} className="changelog-article" aria-label={`Изменения в версии ${release.version}`} tabIndex={0} data-i18n-skip>
    <div className="changelog-article-inner">
      <header className="changelog-release-heading">
        <div className="changelog-release-meta">
          <span className="changelog-version">Версия {release.version}</span>
          {installed && <span className="changelog-installed"><CheckCircle size={12} aria-hidden="true" />Установлена</span>}
          <span className="changelog-date"><Clock size={12} aria-hidden="true" />{release.date ? <time dateTime={release.date}>{releaseDate(release.date)}</time> : releaseDate()}</span>
        </div>
        <h3>{release.title}</h3>
        <p>{release.intro}</p>
      </header>
      {release.highlight && <section className="changelog-highlight" aria-label={release.highlight.label}>
        <div className="changelog-highlight-copy">
          <span className="changelog-eyebrow"><Sparkles size={15} aria-hidden="true" />{release.highlight.label}</span>
          <h4>{release.highlight.title}</h4>
          <p>{release.highlight.description}</p>
        </div>
        {release.highlight.image && <ReleaseFigure image={release.highlight.image} />}
      </section>}
      <div className="changelog-sections">{release.sections.map(section => {
        const Icon = sectionIcons[section.kind];
        return <section className="changelog-section" key={section.title}>
          <h4><span className="changelog-section-icon"><Icon size={17} aria-hidden="true" /></span>{section.title}</h4>
          <ul>{section.items.map(item => <li key={item.title}>
            <h5>{item.title}</h5><p>{item.description}</p>
            {item.image && <ReleaseFigure image={item.image} />}
          </li>)}</ul>
        </section>;
      })}</div>
      {release.note && <aside className="changelog-note"><InfoCircle size={15} aria-hidden="true" /><p>{release.note}</p></aside>}
    </div>
  </article>;
}

function ChangelogContent({ releases, installedVersion, selected, onSelect }: { releases: ReleaseNote[]; installedVersion: string; selected: string; onSelect: (version: string) => void }) {
  const release = releases.find(item => item.version === selected) ?? releases[0];
  return <div className="changelog-layout">
    <div className="changelog-version-bar">
      <span className="changelog-version-label"><Layers size={16} aria-hidden="true" />Версии</span>
      <nav className="changelog-version-list" aria-label="Версии Iris">{releases.map(item => <MaterialButton
        key={item.version} materialKey={`changelog.version.${item.version}`} type="button" appearance={release.version === item.version ? "lens" : "quiet"}
        className={`changelog-version-button${release.version === item.version ? " is-active" : ""}`}
        title={item.version === installedVersion ? "Текущая сборка" : releaseDate(item.date)}
        aria-current={release.version === item.version ? "page" : undefined} onClick={() => onSelect(item.version)}>
        <span>{item.version}</span>
        {item.version === installedVersion && <CheckCircle size={13} aria-hidden="true" />}
      </MaterialButton>)}</nav>
    </div>
    <div className="changelog-mobile-select"><label htmlFor="changelog-version-select">Версия</label><CustomSelect id="changelog-version-select" value={release.version} onChange={event => onSelect(event.target.value)}>{releases.map(item => <option key={item.version} value={item.version}>{item.version}{item.version === installedVersion ? " · Установлена" : ""}</option>)}</CustomSelect></div>
    <ReleaseArticle key={release.version} release={release} installed={release.version === installedVersion} />
  </div>;
}

export function ChangelogDialog({ open, onClose, releases = availableReleases, installedVersion = APP_VERSION }: {
  open: boolean; onClose: () => void; releases?: ReleaseNote[]; installedVersion?: string;
}) {
  const [selected, setSelected] = useState(installedVersion);
  useLayoutEffect(() => { if (open) setSelected(installedVersion); }, [open, installedVersion]);
  const heading = <div className="changelog-window-heading" aria-hidden="true"><BookOpen size={20} /><span>Что нового</span></div>;
  return <AppDialog className="changelog-dialog" open={open} onClose={onClose} title="Что нового" headerContent={heading} variant="info" size="wide" presentation="spotlight">
    {open && <ChangelogContent releases={releases} installedVersion={installedVersion} selected={selected} onSelect={setSelected} />}
  </AppDialog>;
}

export function ChangelogController({ enabled, open, onOpen, onClose }: { enabled: boolean; open: boolean; onOpen: () => void; onClose: () => void }) {
  useEffect(() => { if (enabled) return watchChangelogNotice(); }, [enabled]);
  useEffect(() => {
    window.addEventListener("iris-open-changelog", onOpen);
    return () => window.removeEventListener("iris-open-changelog", onOpen);
  }, [onOpen]);
  useEffect(() => {
    if (open) { acknowledgeChangelog(); notify.dismiss(CHANGELOG_NOTICE_ID); }
  }, [open]);
  return <ChangelogDialog open={open} onClose={onClose} />;
}

export function ChangelogSettingsCard() {
  return <section className="settings-card changelog-settings-card">
    <div className="settings-card-header"><div className="settings-card-title-group">
      <h3 className="settings-card-title">Что нового</h3>
      <p className="settings-card-subtitle">Заметки об обновлениях и прошлые версии Iris.</p>
    </div><span className="changelog-settings-version" data-i18n-skip>{APP_VERSION}</span></div>
    <div className="settings-card-actions"><MaterialButton materialKey="settings.changelog" type="button" className="secondary" onClick={openChangelog}><BookOpen size={17} aria-hidden="true" />История обновлений<ArrowRight size={16} aria-hidden="true" /></MaterialButton></div>
  </section>;
}
