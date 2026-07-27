import { useEffect, useState } from "react";
import { Copy, Menu, Minus, Square, X } from "lucide-react";
import { getCurrentWindow } from "@tauri-apps/api/window";

import { isDesktopApp, quitDesktopApp } from "../desktop";

export function WindowChrome({
  title,
  onOpenNavigation,
  compact = false,
}: {
  title: string;
  onOpenNavigation?: () => void;
  compact?: boolean;
}) {
  const desktop = isDesktopApp();
  const [maximized, setMaximized] = useState(false);

  useEffect(() => {
    if (!desktop) return;
    const window = getCurrentWindow();
    let unlisten: (() => void) | undefined;
    void window.isMaximized().then(setMaximized);
    void window.onResized(async () => setMaximized(await window.isMaximized())).then((stop) => {
      unlisten = stop;
    });
    return () => unlisten?.();
  }, [desktop]);

  const toggleMaximize = async () => {
    const window = getCurrentWindow();
    await window.toggleMaximize();
    setMaximized(await window.isMaximized());
  };

  const handleHeaderDoubleClick = (event: React.MouseEvent<HTMLElement>) => {
    if ((event.target as HTMLElement).closest("button, a, input, textarea, select, [role='button']")) return;
    void toggleMaximize();
  };

  return (
    <header
      className={`window-chrome${compact ? " is-compact" : ""}`}
      data-tauri-drag-region
      onDoubleClick={desktop ? handleHeaderDoubleClick : undefined}
    >
      <div className="window-chrome-title" data-tauri-drag-region>
        {onOpenNavigation && (
          <button className="icon-button menu-toggle" onClick={onOpenNavigation} aria-label="Открыть меню">
            <Menu size={19} aria-hidden="true" />
          </button>
        )}
        {title && <h1 data-tauri-drag-region>{title}</h1>}
      </div>
      <div className="window-chrome-actions">
        {desktop && (
          <div className="window-controls" aria-label="Управление окном">
            <button onClick={() => void getCurrentWindow().minimize()} aria-label="Свернуть окно"><Minus size={14} /></button>
            <button onClick={() => void toggleMaximize()} aria-label={maximized ? "Восстановить окно" : "Развернуть окно"}>
              {maximized ? <Copy size={12} /> : <Square size={12} />}
            </button>
            <button className="window-close" onClick={() => void quitDesktopApp()} aria-label="Закрыть Iris"><X size={15} /></button>
          </div>
        )}
      </div>
    </header>
  );
}
