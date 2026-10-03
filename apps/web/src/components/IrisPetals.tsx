import { useEffect, useId, useRef } from "react";
import petals from "../brand/iris-petals.json";
import lettering from "../brand/iris-lettering.json";
import { shapePetal } from "../brand/irisPetalGeometry";
import { createTimeline, isTestEnvironment, prefersReducedMotion } from "../animations";

function Petal({ index, paint, unfolding, alive, settling }: {
  index: number; paint: string; unfolding: boolean; alive: boolean; settling: boolean;
}) {
  const ref = useRef<SVGGElement>(null);
  const preservePose = useRef(settling);
  preservePose.current = settling;
  const original = petals[index].d;
  useEffect(() => {
    const petal = ref.current;
    const path = petal?.querySelector("path");
    if (!alive || !petal || !path || isTestEnvironment() || prefersReducedMotion()) return;
    // A slow, asymmetric flex from the base. Only completed petals participate;
    // each keeps its own cycle when another startup stage arrives.
    const direction = index === 1 ? -1 : 1;
    const timeline = createTimeline({ loop: true, delay: index * 220 });
    timeline.add(path, {
      d: [
        { from: original, to: shapePetal(original, 1.023, index), duration: 1400, ease: "inOutSine" },
        { to: shapePetal(original, 0.987, index), duration: 1600, ease: "inOutSine" },
        { to: original, duration: 1400, ease: "inOutSine" },
      ],
    }, 0);
    timeline.add(petal, {
      rotate: [0, direction * (index === 0 ? 0.9 : 1.7), direction * -0.45, 0],
      y: [0, -1.3, 0.4, 0], duration: 4400, ease: "inOutSine",
    }, 0);
    return () => {
      timeline.cancel();
      // The finale takes over the current pose and eases it into rest. Errors
      // and ordinary disposal still restore the exact canonical silhouette.
      if (!preservePose.current) {
        path.setAttribute("d", original);
        petal.style.transform = "";
      }
    };
  }, [alive, index, original]);
  return <g ref={ref} data-petal={index} style={unfolding ? { opacity: 0 } : undefined}>
    <path data-petal-shape={index} d={unfolding ? shapePetal(original, 0, index) : original} fill={paint} />
  </g>;
}

/** Exact V3 contours and gradients, extracted from public/brand/iris-logo.svg. */
export function IrisPetals({ unfolding = false, withWordmark = false, withSilhouettes = false, idlePetals = 0, settling = false }: {
  unfolding?: boolean; withWordmark?: boolean; withSilhouettes?: boolean; idlePetals?: number; settling?: boolean;
}) {
  const id = useId().replace(/:/g, "");
  return (
    <svg className={`iris-petals${withWordmark ? " iris-wordmark" : ""}`} viewBox={withWordmark ? "0 0 344 144" : "0 -4 152 152"} fill="none" aria-hidden="true">
      <defs>
        {petals.map((petal, index) => (
          <linearGradient key={index} id={`${id}-paint-${index}`} x1={petal.x1} y1={petal.y1}
            x2={petal.x2} y2={petal.y2} gradientUnits="userSpaceOnUse">
            {petal.stops.map((stop) => <stop key={stop.offset} offset={stop.offset} stopColor={stop.color} />)}
          </linearGradient>
        ))}
        {withWordmark && lettering.map((letter, index) => (
          <linearGradient key={`letter-${index}`} id={`${id}-letter-paint-${index}`} x1={letter.x1} y1={letter.y1}
            x2={letter.x2} y2={letter.y2} gradientUnits="userSpaceOnUse">
            {letter.stops.map((stop) => <stop key={stop.offset} offset={stop.offset} stopColor={stop.color} />)}
          </linearGradient>
        ))}
        {withWordmark && <>
          <linearGradient id={`${id}-letter-feather`} data-letter-reveal
            x1={unfolding ? 120 : 344} y1="0" x2={unfolding ? 152 : 376} y2="0" gradientUnits="userSpaceOnUse">
            <stop offset="0" stopColor="white" />
            <stop offset="1" stopColor="black" />
          </linearGradient>
          <mask id={`${id}-letter-reveal`} maskUnits="userSpaceOnUse" x="144" y="-8" width="212" height="160"
            style={{ maskType: "luminance" }}>
            <rect x="144" y="-8" width="212" height="160" fill={`url(#${id}-letter-feather)`} />
          </mask>
        </>}
      </defs>
      {petals.map((petal, index) => (
        <Petal key={index} index={index} paint={`url(#${id}-paint-${index})`}
          unfolding={unfolding} alive={index < idlePetals} settling={settling} />
      ))}
      {withSilhouettes && <g fill="#fff" opacity="0.075" pointerEvents="none">
        {petals.map((petal, index) => (
          <path key={index} data-petal-silhouette={index} d={petal.d} />
        ))}
      </g>}
      {withWordmark && <g data-wordmark mask={`url(#${id}-letter-reveal)`}>
        {[0, 1, 2, 3].map((letterIndex) => <g key={letterIndex} data-letter={letterIndex}>
          {lettering.map((letter, index) => letter.letter === letterIndex &&
            <path key={index} d={letter.d} fill={`url(#${id}-letter-paint-${index})`} />)}
        </g>)}
      </g>}
    </svg>
  );
}
