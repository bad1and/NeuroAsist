import { lazy, Suspense, useEffect, useRef, useState, type RefObject } from "react";
import { MaterialButton } from "./MaterialButton";
import { IconInterfaceSpirals } from "../CustomIcons";
import type { CoreStatus } from "../desktop";
import type { StartupStage } from "../startup";
import { IrisPetals } from "./IrisPetals";
import petals from "../brand/iris-petals.json";
import { shapePetal } from "../brand/irisPetalGeometry";
import { WindowChrome } from "./WindowChrome";
import { animate, createTimeline, isTestEnvironment, prefersReducedMotion } from "../animations";
import "./StartupScreen.css";

const StartupJump = lazy(() => import("../startup-jump/StartupJump").then((module) => ({ default: module.StartupJump })));

const floraAssetsPromise = Promise.all([
  import("../../../../assets/startup-flora-left.webp"),
  import("../../../../assets/startup-flora-right.webp"),
  import("../../../../assets/startup-flora-left-compact.webp"),
  import("../../../../assets/startup-flora-right-compact.webp"),
  import("../../../../assets/startup-flora-top-right.webp"),
]);

const STAGES = ["Запуск ядра", "Готовность модели", "Запуск сервисов"];
const STATUS_COPY: Record<CoreStatus, { title: string; detail: string }> = {
  starting: { title: "Запускаю Iris", detail: "Подготавливаю ядро" },
  ready: { title: "Рада тебя видеть", detail: "Всё готово к разговору" },
  failed: { title: "Не удалось запустить ядро", detail: "Проверь журнал диагностики или попробуй ещё раз" },
  crashed: { title: "Ядро завершило работу", detail: "Iris сохранила данные и готова к повторному запуску" },
  closing: { title: "Завершаю работу", detail: "Сохраняю состояние и закрываю сервисы" },
};

export function StartupScreen({ status, stage = status === "ready" || status === "closing" ? 3 : 1,
  retrying = false, subdetail, customTitle, onRetry, onReveal, onComplete, revealTarget, onClose,
}: {
  status: CoreStatus;
  stage?: StartupStage;
  retrying?: boolean;
  subdetail?: string;
  customTitle?: string;
  onRetry?: () => void;
  onReveal?: () => void;
  onComplete?: () => void;
  revealTarget?: RefObject<HTMLDivElement | null>;
  onClose?: () => void;
}) {
  const screenRef = useRef<HTMLDivElement>(null);
  const completeRef = useRef(onComplete);
  completeRef.current = onComplete;
  const revealRef = useRef(onReveal);
  revealRef.current = onReveal;
  const [finishPhase, setFinishPhase] = useState<"loading" | "finishing" | "preparing" | "revealing">("loading");
  const [revealed, setRevealed] = useState(0);
  const [gameOpen, setGameOpen] = useState(false);
  const [flora, setFlora] = useState<{ left: string; right: string; leftCompact: string; rightCompact: string; topRight: string } | null>(null);
  const failed = status === "failed" || status === "crashed";
  const canReveal = !failed && revealed < stage;
  const canFinish = status === "ready" && stage === 3 && revealed === 3;
  const revealingInterface = finishPhase === "revealing";
  // Core health can be ready while the model/voice still load. Stop playing
  // on actual readiness, before the existing petal finale and handoff.
  const gameAvailable = !failed && status !== "closing" && !(status === "ready" && stage === 3);

  useEffect(() => {
    if (!gameAvailable) setGameOpen(false);
  }, [gameAvailable]);

  useEffect(() => {
    let active = true;
    void floraAssetsPromise.then(([left, right, leftCompact, rightCompact, topRight]) => {
      if (active) setFlora({ left: left.default, right: right.default,
        leftCompact: leftCompact.default, rightCompact: rightCompact.default, topRight: topRight.default });
    });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    const root = screenRef.current;
    if (!root || isTestEnvironment()) return;
    const reduced = prefersReducedMotion();
    const reveal = root.querySelector("[data-letter-reveal]")!;
    const timeline = createTimeline();
    timeline.add(reveal, { x1: [120, 344], x2: [152, 376], duration: reduced ? 160 : 1450, ease: "inOutCubic" }, reduced ? 0 : 180);
    root.querySelectorAll<SVGGElement>("[data-letter]").forEach((letter, index) => {
      timeline.add(letter, { opacity: [0, 1], y: reduced ? 0 : [5, 0],
        filter: reduced ? "none" : ["blur(3.5px)", "blur(0px)"],
        onComplete: () => { letter.style.filter = ""; },
        duration: reduced ? 160 : 800, ease: "outCubic" }, reduced ? 0 : 300 + index * 140);
    });
    return () => { timeline.cancel(); };
  }, []);

  useEffect(() => {
    if (!flora || isTestEnvironment()) return;
    const root = screenRef.current;
    if (!root) return;
    const reduced = prefersReducedMotion();
    const timeline = createTimeline();
    const sway: ReturnType<typeof animate>[] = [];
    root.querySelectorAll<HTMLElement>(".startup-flora").forEach((plant, index) => {
      const sign = index === 0 ? -1 : 1;
      timeline.add(plant, { opacity: [0, 1], x: reduced ? 0 : [sign * 44, 0],
        duration: reduced ? 160 : 1250, ease: "outCubic" }, reduced ? 0 : index * 120);
      const image = plant.querySelector("img");
      if (image && !reduced) sway.push(animate(image, {
        rotate: [sign * 0.65, sign * -0.65, sign * 0.65],
        x: [0, sign * 3, 0], y: [0, -3, 0], duration: index === 0 ? 6400 : 7200,
        ease: "inOutSine", loop: true,
      }));
    });
    return () => { timeline.cancel(); sway.forEach((animation) => animation.cancel()); };
  }, [flora]);

  // Advance one contour at a time, even when a warm startup reports all stages
  // in the same frame. A slower stage holds the assembled petals in place.
  useEffect(() => {
    if (!canReveal) return;
    const root = screenRef.current;
    const petal = root?.querySelector<SVGGElement>(`[data-petal="${revealed}"]`);
    const path = root?.querySelector<SVGPathElement>(`[data-petal-shape="${revealed}"]`);
    const silhouette = root?.querySelector<SVGPathElement>(`[data-petal-silhouette="${revealed}"]`);
    if (!petal || !path) return;
    const original = petals[revealed].d;
    if (isTestEnvironment()) {
      if (silhouette) silhouette.style.opacity = "0";
      petal.style.opacity = "1";
      path.setAttribute("d", original);
      root?.querySelector("[data-letter-reveal]")?.setAttribute("x1", "344");
      root?.querySelector("[data-letter-reveal]")?.setAttribute("x2", "376");
      setRevealed(revealed + 1);
      return;
    }
    const reduced = prefersReducedMotion();
    const fadeOnly = revealed === 0;
    const unfoldDuration = reduced ? 140 : fadeOnly ? 1300 : 1100;
    if (reduced || fadeOnly) path.setAttribute("d", original);
    const timeline = createTimeline({ onComplete: () => {
      path.setAttribute("d", original);
      setRevealed(revealed + 1);
    } });
    // Keep the silhouette above the petal until its full contour has settled.
    if (silhouette) timeline.add(silhouette, {
      opacity: 0, duration: reduced ? 60 : 240, ease: "outCubic",
    }, unfoldDuration);
    if (!reduced && !fadeOnly) timeline.add(path, {
      d: [
        { from: shapePetal(original, 0, revealed), to: shapePetal(original, 1.035, revealed), duration: 820, ease: "outCubic" },
        { to: original, duration: 280, ease: "inOutSine" },
      ],
    }, 0);
    timeline.add(petal, {
      opacity: [0, 1],
      rotate: reduced || fadeOnly ? 0 : [revealed === 1 ? 7 : -7, 0],
      duration: reduced ? 140 : fadeOnly ? unfoldDuration : 900, ease: "outCubic",
    }, 0);
    return () => { timeline.cancel(); };
  }, [canReveal, revealed]);

  useEffect(() => {
    if (!failed) return;
    const root = screenRef.current;
    root?.querySelectorAll("[data-petal-shape]").forEach((path, index) => path.setAttribute("d", petals[index].d));
    root?.querySelector("[data-letter-reveal]")?.setAttribute("x1", "344");
    root?.querySelector("[data-letter-reveal]")?.setAttribute("x2", "376");
  }, [failed]);

  useEffect(() => {
    if (!canFinish) {
      setFinishPhase("loading");
      return;
    }
    if (!completeRef.current) return;
    const root = screenRef.current;
    if (!root) return;
    setFinishPhase("finishing");
    if (isTestEnvironment()) {
      const timer = window.setTimeout(() => setFinishPhase("preparing"), 0);
      return () => window.clearTimeout(timer);
    }
    const reduced = prefersReducedMotion();
    let active = true;
    const timeline = createTimeline({ onComplete: () => {
      if (active) setFinishPhase("preparing");
    } });
    // Ease out of each petal's actual waiting pose instead of snapping to zero.
    // Keep the full logo visible for the complete closing gesture and pause.
    root.querySelectorAll<SVGGElement>("[data-petal]").forEach((petal, index) => {
      const path = petal.querySelector("path")!;
      timeline.add(path, { d: petals[index].d, duration: reduced ? 120 : 420, ease: "inOutSine" }, 0);
      timeline.add(petal, { y: 0, rotate: 0, duration: reduced ? 120 : 420, ease: "inOutSine" }, 0);
      if (!reduced) {
        const start = 420 + index * 100;
        timeline.add(path, { d: [
          { to: shapePetal(petals[index].d, 1.045, index), duration: 600, ease: "inOutSine" },
          { to: petals[index].d, duration: 800, ease: "inOutSine" },
        ] }, start);
        timeline.add(petal, { y: [0, -5, 0], rotate: [0, index === 1 ? -2.8 : 2.2, 0],
          duration: 1400, ease: "inOutSine" }, start);
      }
    });
    if (!reduced) timeline.add(root.querySelector(".startup-mark")!, {
      scale: [1, 1.035, 1], duration: 1500, ease: "inOutSine",
    }, 420);
    timeline.add({ duration: reduced ? 100 : 180 }, reduced ? 120 : 2020);
    return () => { active = false; timeline.cancel(); };
  }, [canFinish]);

  useEffect(() => {
    if (!canFinish || finishPhase !== "preparing") return;
    // Mount the interface only after the logo has finished. Its first render
    // must not block the closing gesture on a cold startup.
    revealRef.current?.();
    if (isTestEnvironment()) {
      const timer = window.setTimeout(() => setFinishPhase("revealing"), 0);
      return () => window.clearTimeout(timer);
    }
    let frame = 0;
    let paintedFrames = 0;
    const waitForInterface = () => {
      if (!revealTarget || revealTarget.current) {
        paintedFrames += 1;
        if (paintedFrames >= 2) {
          setFinishPhase("revealing");
          return;
        }
      }
      frame = window.requestAnimationFrame(waitForInterface);
    };
    frame = window.requestAnimationFrame(waitForInterface);
    return () => window.cancelAnimationFrame(frame);
  }, [canFinish, finishPhase, revealTarget]);

  useEffect(() => {
    if (!canFinish || finishPhase !== "revealing") return;
    const root = screenRef.current;
    if (!root) return;
    if (isTestEnvironment()) {
      const timer = window.setTimeout(() => completeRef.current?.(), 0);
      return () => window.clearTimeout(timer);
    }
    const reduced = prefersReducedMotion();
    const app = revealTarget?.current;
    let completed = false;
    let active = true;
    const timeline = createTimeline({ onComplete: () => {
      if (!active) return;
      completed = true;
      completeRef.current?.();
    } });
    timeline.add(root.querySelector(".startup-copy")!, {
      opacity: [1, 0], duration: reduced ? 120 : 620, ease: "inOutSine",
    }, 0);
    if (app) timeline.add(app, {
      opacity: [0, 1], duration: reduced ? 220 : 1500, ease: "inOutSine",
    }, reduced ? 0 : 180);
    timeline.add(root, { opacity: [1, 0], duration: reduced ? 220 : 1500, ease: "inOutSine" }, reduced ? 0 : 180);
    return () => {
      active = false;
      timeline.cancel();
      if (!completed) {
        root.style.opacity = "1";
        const copy = root.querySelector<HTMLElement>(".startup-copy");
        if (copy) copy.style.opacity = "1";
        if (app) app.style.opacity = "0";
      }
    };
  }, [canFinish, finishPhase, revealTarget]);

  useEffect(() => {
    if (isTestEnvironment()) return;
    const copy = screenRef.current?.querySelector(".startup-copy");
    if (!copy || revealingInterface) return;
    const reduced = prefersReducedMotion();
    const animation = animate(copy, { opacity: [0.45, 1], y: reduced ? 0 : [5, 0],
      filter: reduced ? "none" : ["blur(2px)", "blur(0px)"], duration: 440, ease: "outCubic",
      onComplete: () => { (copy as HTMLElement).style.filter = ""; },
    });
    return () => { animation.cancel(); };
  }, [status, stage, subdetail, customTitle, canFinish, revealingInterface]);

  const copy = STATUS_COPY[status];
  const waiting = !failed && status !== "closing" && !canFinish;
  return (
    <div className="startup-screen" ref={screenRef} data-stage={stage} data-revealed={revealed} data-phase={finishPhase}>
      <div className="startup-flora startup-flora-left" aria-hidden="true">
        {flora && <picture><source media="(max-width: 700px)" srcSet={flora.leftCompact} /><img src={flora.left} alt="" /></picture>}
      </div>
      <div className="startup-flora startup-flora-right" aria-hidden="true">
        {flora && <picture><source media="(max-width: 700px)" srcSet={flora.rightCompact} /><img src={flora.right} alt="" /></picture>}
      </div>
      <div className="startup-flora startup-flora-top-right" aria-hidden="true">
        {flora && <picture><img src={flora.topRight} alt="" /></picture>}
      </div>
      <WindowChrome title="" compact onClose={onClose} />
      <main className={`startup-content is-${status}`}>
        <div className="startup-mark"><IrisPetals unfolding withWordmark withSilhouettes={!failed} idlePetals={failed || canFinish ? 0 : revealed} settling={canFinish} /></div>
        <div className="startup-copy" role="status" aria-live="polite" aria-atomic="true">
          <h1>{customTitle || (waiting ? "Запускаю Iris" : copy.title)}</h1>
          <p>{subdetail || (waiting ? STAGES[stage - 1] : copy.detail)}</p>
        </div>
        {!failed && status !== "closing" && (
          <ol className="startup-stages" aria-label="Этапы запуска">
            {STAGES.map((label, index) => (
              <li key={label} data-state={revealed > index ? "formed" : "waiting"}
                aria-current={waiting && stage === index + 1 ? "step" : undefined}>
                <span className="startup-stage-index" aria-hidden="true">{String(index + 1).padStart(2, "0")}</span>
                {label}
              </li>
            ))}
          </ol>
        )}
        {failed && (
          <MaterialButton materialKey="StartupScreen.retry" className="primary-button" type="button" onClick={onRetry} disabled={retrying}>
            <IconInterfaceSpirals size={17} aria-hidden="true" />
            {retrying ? "Перезапускаю…" : "Попробовать снова"}
          </MaterialButton>
        )}
      </main>
      {gameAvailable && <div className="startup-game">
        {gameOpen ? <Suspense fallback={null}><StartupJump autoStart /></Suspense>
          : <MaterialButton type="button" materialKey="StartupJump.open" appearance="plain"
            className="startup-game-open" onClick={() => setGameOpen(true)}>Попинать х..</MaterialButton>}
      </div>}
    </div>
  );
}
