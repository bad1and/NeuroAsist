import { useEffect, useState, type RefObject } from "react";

const BASE_WIDTH = 829;
const BASE_HEIGHT = 183.5;
const HORIZONTAL_MARGIN = 32;
const MIN_SCALE = 0.55;
const MAX_SCALE = 1.2;

/**
 * Хук для пропорционального масштабирования блока управления диалогом при изменении размера окна.
 * Управляет CSS-переменной `--dock-scale` на элементе контейнера и возвращает текущий масштаб.
 */
export function useDockScale(containerRef: RefObject<HTMLElement | null>): number {
  const [scale, setScale] = useState<number>(1);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    let pendingUpdate = false;
    let frameId: number | null = null;

    const updateScale = () => {
      if (pendingUpdate) return;
      pendingUpdate = true;

      frameId = window.requestAnimationFrame(() => {
        pendingUpdate = false;
        frameId = null;
        if (!containerRef.current) return;

        const rect = containerRef.current.getBoundingClientRect();
        const width = rect.width;
        const height = rect.height;

        // В тестах jsdom или при скрытом элементе размеры могут быть 0
        if (width <= 0 || height <= 0) {
          containerRef.current.style.setProperty("--dock-scale", "1");
          containerRef.current.style.setProperty("--panel-height", "650px");
          return;
        }

        const availWidth = Math.max(0, width - HORIZONTAL_MARGIN);
        const scaleW = availWidth / BASE_WIDTH;

        // Блок управления не должен занимать более ~32% вертикального пространства панели
        const maxDockHeight = height * 0.32;
        const scaleH = maxDockHeight / BASE_HEIGHT;

        // Масштабируем строго пропорционально (aspect ratio сохраняется)
        const targetScale = Math.min(scaleW, scaleH);
        const clampedScale = Number(
          Math.min(MAX_SCALE, Math.max(MIN_SCALE, targetScale)).toFixed(4)
        );

        containerRef.current.style.setProperty("--dock-scale", clampedScale.toString());
        containerRef.current.style.setProperty("--panel-height", `${height}px`);
        setScale((prev) => (Math.abs(prev - clampedScale) > 0.005 ? clampedScale : prev));
      });

      if (!pendingUpdate) {
        frameId = null;
      }
    };

    updateScale();

    const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(updateScale) : null;
    observer?.observe(el);
    window.addEventListener("resize", updateScale);

    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", updateScale);
      if (frameId !== null && typeof window.cancelAnimationFrame === "function") {
        window.cancelAnimationFrame(frameId);
      }
    };
  }, [containerRef]);

  return scale;
}
