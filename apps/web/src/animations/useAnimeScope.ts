import { useEffect, useRef, type DependencyList, type RefObject } from "react";
import { createScope, Scope, prefersReducedMotion, isTestEnvironment } from "./core";

export type AnimeScopeCallback<T extends HTMLElement = HTMLElement> = (
  scope: Scope,
  rootElement: T,
) => void | (() => void);

/**
 * React hook wrapping Anime.js v4 Scope.
 * Automatically cleans up animations via scope.revert() on unmount or deps change.
 */
export function useAnimeScope<T extends HTMLElement = HTMLElement>(
  setup?: AnimeScopeCallback<T>,
  deps: DependencyList = [],
): RefObject<T | null> {
  const containerRef = useRef<T | null>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el || !setup || isTestEnvironment()) return;

    const scope = createScope({ root: el });
    let cleanupFn: void | (() => void);

    scope.add(() => {
      cleanupFn = setup(scope, el);
    });

    return () => {
      if (typeof cleanupFn === "function") {
        try {
          cleanupFn();
        } catch {
          // ignore error in custom cleanup
        }
      }
      scope.revert();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return containerRef;
}
