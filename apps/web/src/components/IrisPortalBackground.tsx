import { memo, useEffect, useRef } from "react";
import { createTimer, type Timer } from "animejs";
import {
  ShaderMount, grainGradientFragmentShader,
  ShaderFitOptions, getShaderNoiseTexture,
} from "@paper-design/shaders";
import { getMoodVisuals } from "../mood-visuals";
import { audioAnalyzer } from "../audio-analyzer";
import type { VoiceState } from "../types";

export interface IrisPortalBackgroundProps {
  emotion?: string;
  voiceState?: VoiceState;
  loading?: boolean;
  isDialogActive?: boolean;
  showInAppAvatar?: boolean;
  isActive?: boolean;
  className?: string;
}

function hexToRgb(hex: string): [number, number, number] {
  const clean = hex.replace("#", "").trim();
  if (clean.length === 3) {
    const r = parseInt(clean[0] + clean[0], 16) / 255;
    const g = parseInt(clean[1] + clean[1], 16) / 255;
    const b = parseInt(clean[2] + clean[2], 16) / 255;
    return [r, g, b];
  }
  if (clean.length === 6) {
    const r = parseInt(clean.substring(0, 2), 16) / 255;
    const g = parseInt(clean.substring(2, 4), 16) / 255;
    const b = parseInt(clean.substring(4, 6), 16) / 255;
    return [r, g, b];
  }
  return [0.77, 0.71, 0.99]; // Default soft iris lavender
}

function srgbToLinear(c: number): number {
  return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
}

function linearToSrgb(c: number): number {
  const clamped = Math.max(0, Math.min(1, c));
  return clamped <= 0.0031308 ? clamped * 12.92 : 1.055 * Math.pow(clamped, 1 / 2.4) - 0.055;
}

// Convert sRGB [0..1] to Oklab [L, a, b]
function rgbToOklab(r: number, g: number, b: number): [number, number, number] {
  const lr = srgbToLinear(r);
  const lg = srgbToLinear(g);
  const lb = srgbToLinear(b);

  const l_ = Math.cbrt(0.4122214708 * lr + 0.5363325363 * lg + 0.0514459929 * lb);
  const m_ = Math.cbrt(0.2119034982 * lr + 0.6806995451 * lg + 0.1073969566 * lb);
  const s_ = Math.cbrt(0.0883024619 * lr + 0.2817188376 * lg + 0.6299787005 * lb);

  const L = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_;
  const a = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_;
  const b_val = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_;

  return [L, a, b_val];
}

// Convert Oklab [L, a, b] to sRGB [0..1]
function oklabToRgb(L: number, a: number, b: number): [number, number, number] {
  const l_ = L + 0.3963377774 * a + 0.2158037573 * b;
  const m_ = L - 0.1055613458 * a - 0.0638541728 * b;
  const s_ = L - 0.0894841775 * a - 1.2914855480 * b;

  const l = l_ * l_ * l_;
  const m = m_ * m_ * m_;
  const s = s_ * s_ * s_;

  const lr = +4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s;
  const lg = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s;
  const lb = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s;

  return [linearToSrgb(lr), linearToSrgb(lg), linearToSrgb(lb)];
}

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

// Paper supplies only the grain functions and noise texture. Iris owns the
// complete wave geometry, spectral color mixing, and audio-reactive parameters.
const PAPER_GRAIN_HELPERS = grainGradientFragmentShader.slice(
  0, grainGradientFragmentShader.indexOf("void main()"),
).replace("precision lowp float;", "precision highp float;");
const IRIS_GRAIN_WAVE_SHADER = `${PAPER_GRAIN_HELPERS}
uniform float u_irisTime;
uniform vec2 u_mouse;
uniform vec2 u_center;
uniform vec3 u_colorCore;
uniform vec3 u_colorFringe;
uniform vec3 u_colorAccent;
uniform float u_radius;
uniform float u_warp;
uniform float u_audioLow;
uniform float u_audioMid;
uniform float u_audioHigh;
uniform float u_audioLevel;
float sdArc(vec2 p, vec2 center, float radius, float width, float warp) {
    float w1 = sin(p.x * 2.4 + u_irisTime * 0.45) * warp;
    float w2 = (sin(p.y * 2.2 + u_irisTime * 0.35) * cos(p.x * 1.7 - u_irisTime * 0.25)) * (warp * 0.85);
    p.y += w1;
    p.x += w2;
    float d = length(p - center) - radius;
    return abs(d) - width;
}

void main() {
    vec2 uv = gl_FragCoord.xy / u_resolution.xy;
    vec2 st = uv;
    float aspect = u_resolution.x / u_resolution.y;
    st.x *= aspect;

    vec2 center = u_center;
    center.x *= aspect;

    vec2 mouseOffset = (u_mouse - 0.5) * 0.04;
    st += mouseOffset;

    // Audio reactive dynamics
    float dynRadius = u_radius + (u_audioLow * 0.18) + (sin(u_irisTime * 0.8) * 0.012);
    float dynWarp = u_warp + (u_audioMid * 0.25);
    float dynIntensity = u_intensity + (u_audioHigh * 0.4) + (u_audioLevel * 0.3);

    // Dual organic arcs
    float d1 = sdArc(st, center, dynRadius, 0.022 + u_audioLow * 0.012, dynWarp);
    float d2 = sdArc(st, center, dynRadius + 0.055 + u_audioMid * 0.03, 0.06 + u_audioMid * 0.02, dynWarp * 1.35);

    float distToCenter = length(st - center);
    float wash = (1.0 - smoothstep(0.0, dynRadius * 2.2, distToCenter)) * 0.22;

    // Glow distributions
    float coreGlow = exp(-max(0.0, d1) * (26.0 - u_audioHigh * 7.0));
    float fringeGlow = exp(-max(0.0, d2) * 8.8);

    // Subtle multi-spectral dispersion along the organic arc
    float angle = atan(st.y - center.y, st.x - center.x);
    float spectralMod = sin(angle * 3.0 + u_irisTime * 0.5) * 0.12 + 0.88;
    
    // Iris signature violet undertone for brand harmony
    vec3 irisBaseViolet = vec3(0.412, 0.357, 0.525);

    vec3 finalColor = vec3(0.0);
    finalColor += u_colorCore * (coreGlow * (1.35 + u_audioHigh * 0.65));
    finalColor += mix(u_colorFringe, u_colorCore, 0.25 * spectralMod) * (fringeGlow * (1.15 + u_audioMid * 0.45));
    finalColor += u_colorAccent * (wash * (0.85 + u_audioLevel * 0.5));
    finalColor += mix(u_colorFringe, irisBaseViolet, 0.20) * wash * (sin(u_irisTime * 0.65) * 0.20 + 0.80);

    // Paper's original multi-scale grain field; it changes pigment coverage,
    // while sdArc above remains Iris's original moving, audio-reactive wave.
    vec2 grain_uv = (gl_FragCoord.xy - 0.5 * u_resolution) * 0.7;
    float baseNoise = snoise(grain_uv * .5);
    vec4 fbmVals = fbmR(.002 * grain_uv + 10., .003 * grain_uv,
                       .001 * grain_uv, rotate(.4 * grain_uv, 2.));
    float grainDist = baseNoise * snoise(grain_uv * .2) - fbmVals.x - fbmVals.y;
    float rawNoise = .75 * baseNoise - fbmVals.w - fbmVals.z;
    float noise = clamp(rawNoise, 0., 1.);

    float coverage = clamp(coreGlow * 1.55 + fringeGlow * 0.95 + wash * 0.80, 0., 1.);
    // Use Paper's field displacement and anti-aliased coverage threshold. Applying
    // a tiny brightness multiplier alone loses the characteristic granular edge.
    float shape = coverage * .35;
    shape += .5 * 2. / 3. * (grainDist + .5);
    shape += u_noise * 10. / 3. * noise;
    float aa = fwidth(shape);
    shape = clamp(shape - .5 / 3., 0., 1.);
    float totalShape = smoothstep(0., .5 + 2. * aa, clamp(shape * 3., 0., 1.));
    float alpha = totalShape * smoothstep(0., .12, coverage);
    // Ink keeps its original core/fringe/accent mixture without whitening the
    // overlapping colors. The grain fades with the wave onto transparent graphite.
    vec3 pigment = finalColor / max(1., max(finalColor.r, max(finalColor.g, finalColor.b)));
    pigment *= .92 * (1. - u_noise * .35 * noise);
    alpha = clamp(alpha * dynIntensity * .90, 0., .95);
    fragColor = vec4(pigment * alpha, alpha);
}
`;

export const IrisPortalBackground = memo(function IrisPortalBackground({
  emotion = "neutral",
  voiceState = "idle",
  loading = false,
  isDialogActive = false,
  showInAppAvatar = false,
  isActive = true,
  className = "",
}: IrisPortalBackgroundProps) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const timerRef = useRef<Timer | null>(null);
  const resetTimeRef = useRef<(() => void) | null>(null);

  // References for live smooth interpolation without re-binding WebGL
  const stateRef = useRef({
    emotion,
    voiceState,
    loading,
    isDialogActive,
    showInAppAvatar,
    isActive,
  });

  useEffect(() => {
    const wasActive = stateRef.current.isActive;
    stateRef.current = {
      emotion,
      voiceState,
      loading,
      isDialogActive,
      showInAppAvatar,
      isActive,
    };
    if (isActive && !wasActive && timerRef.current && !document.hidden) {
      if (resetTimeRef.current) resetTimeRef.current();
      timerRef.current.resume();
    } else if (!isActive) {
      timerRef.current?.pause();
    }
  }, [emotion, voiceState, loading, isDialogActive, showInAppAvatar, isActive]);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return undefined;
    // Paper's 2x sampling is essential: downsampling makes its fine grain coarse.
    // Keep a finite pixel budget and let the Anime timer cap the frame rate.
    let mount: ShaderMount | null = null;
    const noiseTexture = getShaderNoiseTexture();
    let disposed = false;
    const initialize = () => {
      if (disposed) return;
      try {
        mount = new ShaderMount(host, IRIS_GRAIN_WAVE_SHADER, {
          u_irisTime: 0,
          u_colorCore: hexToRgb(getMoodVisuals(stateRef.current.emotion).colors[0]),
          u_colorFringe: hexToRgb(getMoodVisuals(stateRef.current.emotion).colors[1]),
          u_colorAccent: hexToRgb(getMoodVisuals(stateRef.current.emotion).colors[2]),
          u_radius: 0.54, u_warp: getMoodVisuals(stateRef.current.emotion).warp,
          u_intensity: 1, u_noise: 0.25,
          u_audioLow: 0, u_audioMid: 0, u_audioHigh: 0, u_audioLevel: 0,
          u_mouse: [0.5, 0.5],
          u_center: [stateRef.current.showInAppAvatar && stateRef.current.isDialogActive ? -0.08 : 0, 0.95],
          u_fit: ShaderFitOptions.contain,
          u_scale: 1, u_rotation: 0,
          u_originX: 0.5, u_originY: 0.5,
          u_offsetX: 0, u_offsetY: 0,
          u_worldWidth: 0, u_worldHeight: 0,
          u_noiseTexture: noiseTexture,
        }, { alpha: true, antialias: false, depth: false, stencil: false,
             premultipliedAlpha: true, powerPreference: "high-performance" },
        0, 0, 2, 4_000_000);
        mount.canvasElement.className = "iris-portal-canvas";
      } catch {
        // Keep the rest of the conversation usable when WebGL2 is unavailable.
        host.querySelector("canvas")?.remove();
      }
    };
    if (!noiseTexture || (noiseTexture.complete && noiseTexture.naturalWidth > 0)) {
      initialize();
    } else {
      noiseTexture.addEventListener("load", initialize, { once: true });
    }

    // Helper: convert hex to OKLab triple
    const hexToOklab = (hex: string): [number, number, number] => {
      const [r, g, b] = hexToRgb(hex);
      return rgbToOklab(r, g, b);
    };

    const getMoodOklab = (emo: string) => {
      const visuals = getMoodVisuals(emo);
      return {
        visuals,
        coreLab: hexToOklab(visuals.colors[0]),
        fringeLab: hexToOklab(visuals.colors[1]),
        accentLab: hexToOklab(visuals.colors[2]),
      };
    };

    // Pre-calculated fallback colors in OKLab
    const errorCoreLab = rgbToOklab(0.98, 0.38, 0.42);
    const errorFringeLab = rgbToOklab(0.86, 0.14, 0.28);
    const errorAccentLab = rgbToOklab(0.42, 0.08, 0.38);

    let cachedEmotion = emotion;
    let cachedMood = getMoodOklab(emotion);

    // Current OKLab coordinates maintained directly as scalars (zero array allocations per frame)
    let currCoreL = cachedMood.coreLab[0];
    let currCoreA = cachedMood.coreLab[1];
    let currCoreB = cachedMood.coreLab[2];

    let currFringeL = cachedMood.fringeLab[0];
    let currFringeA = cachedMood.fringeLab[1];
    let currFringeB = cachedMood.fringeLab[2];

    let currAccentL = cachedMood.accentLab[0];
    let currAccentA = cachedMood.accentLab[1];
    let currAccentB = cachedMood.accentLab[2];

    let currWarp = cachedMood.visuals.warp;
    let currSpeed = cachedMood.visuals.speed;
    let currRadius = 0.54;
    let currIntensity = 1.0;
    const initialDialogActive = stateRef.current.isDialogActive;
    let currCenterX = (initialDialogActive && stateRef.current.showInAppAvatar) ? -0.08 : 0.0;
    let currCenterY = 0.95;

    let targetMouseX = 0.50;
    let targetMouseY = 0.50;
    let currMouseX = 0.50;
    let currMouseY = 0.50;

    let cachedRect = host.getBoundingClientRect();
    const updateRect = () => { cachedRect = host.getBoundingClientRect(); };
    const handleMouseMove = (event: MouseEvent) => {
      if (cachedRect.width > 0 && cachedRect.height > 0) {
        targetMouseX = Math.max(0, Math.min(1, (event.clientX - cachedRect.left) / cachedRect.width));
        targetMouseY = Math.max(0, Math.min(1, 1 - (event.clientY - cachedRect.top) / cachedRect.height));
      }
    };
    window.addEventListener("mousemove", handleMouseMove, { passive: true });
    const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(updateRect) : null;
    observer?.observe(host);
    let lastTime = performance.now();
    let accumulatedTime = 0;
    let wasSpeaking = false;
    resetTimeRef.current = () => { lastTime = performance.now(); };

    const render = (now: number) => {
      const state = stateRef.current;
      if (!state.isActive || (typeof document !== "undefined" && document.hidden)) {
        timerRef.current?.pause();
        return;
      }

      const dt = Math.min(0.05, Math.max(0.001, (now - lastTime) / 1000));
      lastTime = now;

      if (state.emotion !== cachedEmotion) {
        cachedEmotion = state.emotion;
        cachedMood = getMoodOklab(state.emotion);
      }

      const currentVisuals = cachedMood.visuals;
      let targetCoreLab = cachedMood.coreLab;
      let targetFringeLab = cachedMood.fringeLab;
      let targetAccentLab = cachedMood.accentLab;

      let targetWarp = currentVisuals.warp;
      let targetSpeed = currentVisuals.speed;
      let targetRadius = 0.54;
      let targetIntensity = 1.0;

      // Determine status target
      if (state.voiceState === "speaking") {
        targetRadius = 0.56;
        targetSpeed *= 1.08;
        targetIntensity = 1.08;
      } else if (state.voiceState === "thinking" || state.voiceState === "transcribing" || state.loading) {
        targetRadius = 0.54;
        targetSpeed *= 1.05;
        targetWarp = currentVisuals.warp;
        targetIntensity = 1.10;
      } else if (state.voiceState === "recording") {
        targetRadius = 0.48;
        targetSpeed *= 1.4;
        targetIntensity = 1.15;
      } else if (state.voiceState === "error") {
        targetRadius = 0.52;
        targetSpeed = 1.6;
        targetIntensity = 1.4;
        targetCoreLab = errorCoreLab;
        targetFringeLab = errorFringeLab;
        targetAccentLab = errorAccentLab;
      } else if (!state.isDialogActive) {
        targetRadius = 0.52;
        targetSpeed *= 0.75;
        targetIntensity = 0.85;
      }

      // Center portal halo in top-left
      let targetCenterX = 0.0;
      let targetCenterY = 0.95;
      if (state.showInAppAvatar && state.isDialogActive) {
        targetCenterX = -0.08; // Top-left behind avatar
        targetCenterY = 0.95;
      } else if (state.showInAppAvatar && !state.isDialogActive) {
        targetCenterX = 0.0;
        targetCenterY = 0.95;
      }

      // Phase-staggered scalar color transition in OKLab space (zero array allocations):
      // 1. Fringe/Halo wave reacts first
      const fringeFactor = Math.min(1.0, dt * 5.4);
      currFringeL = lerp(currFringeL, targetFringeLab[0], fringeFactor);
      currFringeA = lerp(currFringeA, targetFringeLab[1], fringeFactor);
      currFringeB = lerp(currFringeB, targetFringeLab[2], fringeFactor);

      // 2. Core filament follows
      const coreFactor = Math.min(1.0, dt * 3.8);
      currCoreL = lerp(currCoreL, targetCoreLab[0], coreFactor);
      currCoreA = lerp(currCoreA, targetCoreLab[1], coreFactor);
      currCoreB = lerp(currCoreB, targetCoreLab[2], coreFactor);

      // 3. Ambient atmospheric wash follows
      const accentFactor = Math.min(1.0, dt * 2.4);
      currAccentL = lerp(currAccentL, targetAccentLab[0], accentFactor);
      currAccentA = lerp(currAccentA, targetAccentLab[1], accentFactor);
      currAccentB = lerp(currAccentB, targetAccentLab[2], accentFactor);

      const dynamicFactor = Math.min(1.0, dt * 4.2);
      currWarp = lerp(currWarp, targetWarp, dynamicFactor);
      currSpeed = lerp(currSpeed, targetSpeed, dynamicFactor);
      currRadius = lerp(currRadius, targetRadius, dynamicFactor);
      currIntensity = lerp(currIntensity, targetIntensity, dynamicFactor);
      currCenterX = lerp(currCenterX, targetCenterX, dynamicFactor);
      currCenterY = lerp(currCenterY, targetCenterY, dynamicFactor);

      // Mouse smooth tracking
      currMouseX = lerp(currMouseX, targetMouseX, Math.min(1.0, dt * 6.0));
      currMouseY = lerp(currMouseY, targetMouseY, Math.min(1.0, dt * 6.0));

      accumulatedTime += dt * currSpeed;

      // Audio frequency spectrum from analyzer
      const isSpeaking = state.voiceState === "speaking";
      if (!isSpeaking && wasSpeaking) audioAnalyzer.reset();
      wasSpeaking = isSpeaking;
      const measuredBands = isSpeaking
        ? audioAnalyzer.getAudioBands()
        : { low: 0, mid: 0, high: 0, level: 0 };
      // The portal follows real browser playback when available. Unity-owned
      // playback has no browser signal, so keep only a restrained presence
      // pulse instead of letting the generic speaking state overdrive it.
      const presence = isSpeaking ? 0.045 : 0;
      const bands = {
        low: Math.min(0.32, measuredBands.low * 0.55 + presence),
        mid: Math.min(0.32, measuredBands.mid * 0.55 + presence),
        high: Math.min(0.26, measuredBands.high * 0.45 + presence * 0.65),
        level: Math.min(0.28, measuredBands.level * 0.55 + presence),
      };

      const core = oklabToRgb(currCoreL, currCoreA, currCoreB);
      const fringe = oklabToRgb(currFringeL, currFringeA, currFringeB);
      const accent = oklabToRgb(currAccentL, currAccentA, currAccentB);
      mount?.setUniforms({
        u_irisTime: accumulatedTime,
        u_colorCore: core, u_colorFringe: fringe, u_colorAccent: accent,
        u_radius: currRadius, u_warp: currWarp, u_intensity: currIntensity,
        u_mouse: [currMouseX, currMouseY], u_center: [currCenterX, currCenterY],
        u_audioLow: bands.low, u_audioMid: bands.mid,
        u_audioHigh: bands.high, u_audioLevel: bands.level,
      });

    };

    const timer = createTimer({
      loop: true,
      frameRate: 40,
      autoplay: false,
      onUpdate: () => render(performance.now()),
    });
    timerRef.current = timer;

    const handleVisibility = () => {
      if (document.hidden) {
        timer.pause();
      } else if (stateRef.current.isActive) {
        lastTime = performance.now();
        timer.resume();
      }
    };

    document.addEventListener("visibilitychange", handleVisibility);

    if (stateRef.current.isActive && !document.hidden) {
      timer.resume();
    }

    return () => {
      document.removeEventListener("visibilitychange", handleVisibility);
      window.removeEventListener("mousemove", handleMouseMove);
      observer?.disconnect();
      timer.cancel();
      timerRef.current = null;
      resetTimeRef.current = null;
      disposed = true;
      noiseTexture?.removeEventListener("load", initialize);
      mount?.dispose();
    };
  }, []);

  return (
    <div className={`iris-portal-backdrop ${className}`.trim()} data-emotion={emotion} aria-hidden="true">
      <div ref={hostRef} className="iris-portal-shader" />
    </div>
  );
});
