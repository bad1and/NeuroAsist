import { useEffect, useLayoutEffect, useState, type RefObject } from "react";

const BASE_WIDTH = 829;
const BASE_HEIGHT = 183.5;
const HORIZONTAL_MARGIN = 32;
const MIN_SCALE = 0.55;
const MAX_SCALE = 1.2;

let lastKnownScale = 1;
let lastKnownHeight = 650;

export function resetLastKnownScaleForTesting(): void {
  lastKnownScale = 1;
  lastKnownHeight = 650;
}

function computeClampedScale(width: number, height: number): number {
  const availWidth = Math.max(0, width - HORIZONTAL_MARGIN);
  const scaleW = availWidth / BASE_WIDTH;
  const maxDockHeight = height * 0.32;
  const scaleH = maxDockHeight / BASE_HEIGHT;
  const targetScale = Math.min(scaleW, scaleH);
  return Number(Math.min(MAX_SCALE, Math.max(MIN_SCALE, targetScale)).toFixed(4));
}

/**
 * Хук для пропорционального масштабирования блока управления диалогом при изменении размера окна.
 * Управляет CSS-переменной `--dock-scale` на элементе контейнера и возвращает текущий масштаб.
 */
export function useDockScale(containerRef: RefObject<HTMLElement | null>): number {
  const [scale, setScale] = useState<number>(() => lastKnownScale);

  // Synchronously compute scale in useLayoutEffect so CSS variable --dock-scale
  // is set BEFORE child layout effects (e.g. InAppAvatarHost) measure their bounding boxes.
  useLayoutEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    if (rect.width > 0 && rect.height > 0) {
      const clamped = computeClampedScale(rect.width, rect.height);
      lastKnownScale = clamped;
      lastKnownHeight = Math.round(rect.height);
      el.style.setProperty("--dock-scale", clamped.toString());
      el.style.setProperty("--panel-height", `${rect.height}px`);
      setScale((prev) => (Math.abs(prev - clamped) > 0.005 ? clamped : prev));
    } else {
      el.style.setProperty("--dock-scale", lastKnownScale.toString());
      el.style.setProperty("--panel-height", `${lastKnownHeight}px`);
    }
  }, [containerRef]);

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
          containerRef.current.style.setProperty("--dock-scale", lastKnownScale.toString());
          containerRef.current.style.setProperty("--panel-height", `${lastKnownHeight}px`);
          return;
        }

        const clampedScale = computeClampedScale(width, height);
        lastKnownScale = clampedScale;
        lastKnownHeight = Math.round(height);

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
