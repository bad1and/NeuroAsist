import { useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  IconImagePictureLandscape1 as ImageIcon, IconInterfaceChevronLeft as ChevronLeft,
  IconInterfaceChevronRight as ChevronRight, IconInterfaceExpand as Expand,
} from "../CustomIcons";
import { OVERVIEW_ARTWORKS } from "../overview-art";
import { animate, isTestEnvironment, prefersReducedMotion } from "../animations";
import { AppDialog } from "./AppDialog";
import { MaterialButton } from "./MaterialButton";

export function ArtworkImage({ src, alt, className, position }: { src: string; alt: string; className?: string; position?: string }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => { setFailed(false); }, [src]);
  return failed ? <span className={`overview-image-missing ${className ?? ""}`} role="img" aria-label={alt}>
    <ImageIcon size={28} aria-hidden="true" /><span>Изображение недоступно</span>
  </span> : <img className={className} src={src} alt={alt} style={{ objectPosition: position }} onError={() => setFailed(true)} draggable={false} />;
}

export function OverviewGallery({ isActive }: { isActive: boolean }) {
  const [start, setStart] = useState(0);
  const [selected, setSelected] = useState<number | null>(null);
  const trackRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<HTMLDivElement>(null);
  const opened = selected !== null;
  const artwork = OVERVIEW_ARTWORKS[selected ?? 0];
  const count = OVERVIEW_ARTWORKS.length;
  const move = (direction: number) => setStart(value => (value + direction + count) % count);
  const select = (direction: number) => setSelected(value => value === null ? null : (value + direction + count) % count);

  useEffect(() => { if (!isActive) setSelected(null); }, [isActive]);
  useLayoutEffect(() => {
    if (!trackRef.current || isTestEnvironment()) return;
    const motion = animate(trackRef.current, { opacity: [.5, 1], translateX: prefersReducedMotion() ? 0 : [8, 0], duration: prefersReducedMotion() ? 100 : 220, ease: "outQuad" });
    return () => { motion.revert(); };
  }, [start]);
  useLayoutEffect(() => {
    if (!opened || !viewerRef.current || isTestEnvironment()) return;
    const motion = animate(viewerRef.current, { opacity: [.4, 1], duration: prefersReducedMotion() ? 100 : 180, ease: "outQuad" });
    return () => { motion.revert(); };
  }, [selected, opened]);

  return <section className="overview-gallery overview-reveal" aria-label="Галерея" aria-roledescription="карусель" onKeyDown={event => {
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    if (event.key === "ArrowLeft") { event.preventDefault(); opened ? select(-1) : move(-1); }
    if (event.key === "ArrowRight") { event.preventDefault(); opened ? select(1) : move(1); }
  }}>
    <header className="overview-section-heading">
      <div className="overview-gallery-controls" role="group" aria-label="Перелистывание галереи">
        <MaterialButton type="button" materialKey="overview.gallery.previous" className="icon-button" appearance="quiet" aria-label="Предыдущие изображения" onClick={() => move(-1)} disabled={count < 2}><ChevronLeft size={19} aria-hidden="true" /></MaterialButton>
        <MaterialButton type="button" materialKey="overview.gallery.next" className="icon-button" appearance="quiet" aria-label="Следующие изображения" onClick={() => move(1)} disabled={count < 2}><ChevronRight size={19} aria-hidden="true" /></MaterialButton>
      </div>
    </header>
    <div className="overview-gallery-window">
      <div className="overview-gallery-track" ref={trackRef}>
        {OVERVIEW_ARTWORKS.slice(0, 2).map((_, offset) => {
          const index = (start + offset) % count;
          const item = OVERVIEW_ARTWORKS[index];
          return <MaterialButton key={offset} type="button" materialKey={`overview.gallery.slot.${offset}`} appearance="plain" className="overview-artwork" aria-label={`Открыть изображение: ${item.title}`} onClick={() => setSelected(index)}>
            <span className="overview-artwork-image"><ArtworkImage src={item.src} alt={item.description} position={item.position} /><Expand className="overview-artwork-expand" size={18} aria-hidden="true" /></span>
          </MaterialButton>;
        })}
      </div>
    </div>
    <AppDialog open={opened} onClose={() => setSelected(null)} title={artwork.title} description={artwork.author} icon={<ImageIcon size={22} aria-hidden="true" />} variant="info" presentation="spotlight" size="wide" showRim={false} className="overview-gallery-dialog">
      <div className="overview-artwork-viewer" ref={viewerRef}>
        <ArtworkImage src={artwork.src} alt={artwork.description} />
      </div>
      <footer className="overview-viewer-footer">
        <span aria-live="polite" aria-atomic="true">{(selected ?? 0) + 1} / {count}</span>
        <div className="overview-gallery-controls" role="group" aria-label="Просмотр изображений" onKeyDown={event => {
          if (event.altKey || event.ctrlKey || event.metaKey) return;
          if (event.key === "ArrowLeft") { event.preventDefault(); event.stopPropagation(); select(-1); }
          if (event.key === "ArrowRight") { event.preventDefault(); event.stopPropagation(); select(1); }
        }}>
          <MaterialButton materialKey="overview.viewer.previous" type="button" className="icon-button" appearance="quiet" aria-label="Предыдущее изображение" onClick={() => select(-1)} disabled={count < 2}><ChevronLeft size={20} aria-hidden="true" /></MaterialButton>
          <MaterialButton materialKey="overview.viewer.next" type="button" className="icon-button" appearance="quiet" aria-label="Следующее изображение" onClick={() => select(1)} disabled={count < 2}><ChevronRight size={20} aria-hidden="true" /></MaterialButton>
        </div>
      </footer>
    </AppDialog>
  </section>;
}
