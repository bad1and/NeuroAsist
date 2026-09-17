import { memo, useEffect, useRef } from "react";
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

const VERTEX_SHADER_SOURCE = `
attribute vec2 a_position;
void main() {
    gl_Position = vec4(a_position, 0.0, 1.0);
}
`;

const FRAGMENT_SHADER_SOURCE = `
precision highp float;

uniform vec2 u_resolution;
uniform float u_time;
uniform vec2 u_mouse;
uniform vec2 u_center;

uniform vec3 u_colorCore;
uniform vec3 u_colorFringe;
uniform vec3 u_colorAccent;

uniform float u_radius;
uniform float u_warp;
uniform float u_intensity;

uniform float u_audioLow;
uniform float u_audioMid;
uniform float u_audioHigh;
uniform float u_audioLevel;
uniform float u_statusMode; // 0=idle, 1=listening, 2=thinking, 3=speaking

float sdArc(vec2 p, vec2 center, float radius, float width, float warp) {
    float w1 = sin(p.x * 2.4 + u_time * 0.45) * warp;
    float w2 = (sin(p.y * 2.2 + u_time * 0.35) * cos(p.x * 1.7 - u_time * 0.25)) * (warp * 0.85);
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
    float dynRadius = u_radius + (u_audioLow * 0.18) + (sin(u_time * 0.8) * 0.012);
    float dynWarp = u_warp + (u_audioMid * 0.25);
    float dynIntensity = u_intensity + (u_audioHigh * 0.4) + (u_audioLevel * 0.3);

    // Dual organic arcs
    float d1 = sdArc(st, center, dynRadius, 0.022 + u_audioLow * 0.012, dynWarp);
    float d2 = sdArc(st, center, dynRadius + 0.055 + u_audioMid * 0.03, 0.06 + u_audioMid * 0.02, dynWarp * 1.35);

    float distToCenter = length(st - center);
    float wash = smoothstep(dynRadius * 2.2, 0.0, distToCenter) * 0.22;

    // Glow distributions
    float coreGlow = exp(-max(0.0, d1) * (26.0 - u_audioHigh * 7.0));
    float fringeGlow = exp(-max(0.0, d2) * 8.8);

    // Subtle multi-spectral dispersion along the organic arc
    float angle = atan(st.y - center.y, st.x - center.x);
    float spectralMod = sin(angle * 3.0 + u_time * 0.5) * 0.12 + 0.88;
    
    // Iris signature violet undertone for brand harmony
    vec3 irisBaseViolet = vec3(0.412, 0.357, 0.525);

    vec3 finalColor = vec3(0.0);
    finalColor += u_colorCore * (coreGlow * (1.35 + u_audioHigh * 0.65));
    finalColor += mix(u_colorFringe, u_colorCore, 0.25 * spectralMod) * (fringeGlow * (1.15 + u_audioMid * 0.45));
    finalColor += u_colorAccent * (wash * (0.85 + u_audioLevel * 0.5));
    finalColor += mix(u_colorFringe, irisBaseViolet, 0.20) * wash * (sin(u_time * 0.65) * 0.20 + 0.80);

    float alpha = clamp((coreGlow * 1.55 + fringeGlow * 0.95 + wash * 0.80), 0.0, 1.0);
    vec3 toneMapped = vec3(1.0) - exp(-finalColor * (1.65 * dynIntensity));

    gl_FragColor = vec4(toneMapped, alpha * 0.95);
}
`;

function createShader(gl: WebGLRenderingContext, type: number, source: string): WebGLShader | null {
  const shader = gl.createShader(type);
  if (!shader) return null;
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    gl.deleteShader(shader);
    return null;
  }
  return shader;
}

function createProgram(gl: WebGLRenderingContext, vsSource: string, fsSource: string): WebGLProgram | null {
  const vs = createShader(gl, gl.VERTEX_SHADER, vsSource);
  const fs = createShader(gl, gl.FRAGMENT_SHADER, fsSource);
  if (!vs || !fs) return null;

  const program = gl.createProgram();
  if (!program) return null;
  gl.attachShader(program, vs);
  gl.attachShader(program, fs);
  gl.linkProgram(program);

  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    gl.deleteProgram(program);
    return null;
  }
  return program;
}

export const IrisPortalBackground = memo(function IrisPortalBackground({
  emotion = "neutral",
  voiceState = "idle",
  loading = false,
  isDialogActive = false,
  showInAppAvatar = false,
  isActive = true,
  className = "",
}: IrisPortalBackgroundProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const animationFrameRef = useRef<number | null>(null);
  const renderCallbackRef = useRef<((now: number) => void) | null>(null);
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
    if (isActive && !wasActive && renderCallbackRef.current) {
      if (resetTimeRef.current) resetTimeRef.current();
      if (animationFrameRef.current === null) {
        animationFrameRef.current = requestAnimationFrame(renderCallbackRef.current);
      }
    }
  }, [emotion, voiceState, loading, isDialogActive, showInAppAvatar, isActive]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;

    let gl: WebGLRenderingContext | null = null;
    try {
      gl = canvas.getContext("webgl", {
        alpha: true,
        antialias: true,
        premultipliedAlpha: false,
        powerPreference: "high-performance",
      });
    } catch {
      return undefined;
    }
    if (!gl) return undefined;

    const program = createProgram(gl, VERTEX_SHADER_SOURCE, FRAGMENT_SHADER_SOURCE);
    if (!program) return undefined;

    gl.useProgram(program);

    // Fullscreen quad buffer
    const positionBuffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, positionBuffer);
    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]),
      gl.STATIC_DRAW,
    );

    const aPositionLocation = gl.getAttribLocation(program, "a_position");
    gl.enableVertexAttribArray(aPositionLocation);
    gl.vertexAttribPointer(aPositionLocation, 2, gl.FLOAT, false, 0, 0);

    // Uniform locations
    const uResLoc = gl.getUniformLocation(program, "u_resolution");
    const uTimeLoc = gl.getUniformLocation(program, "u_time");
    const uMouseLoc = gl.getUniformLocation(program, "u_mouse");
    const uCenterLoc = gl.getUniformLocation(program, "u_center");
    const uColorCoreLoc = gl.getUniformLocation(program, "u_colorCore");
    const uColorFringeLoc = gl.getUniformLocation(program, "u_colorFringe");
    const uColorAccentLoc = gl.getUniformLocation(program, "u_colorAccent");
    const uRadiusLoc = gl.getUniformLocation(program, "u_radius");
    const uWarpLoc = gl.getUniformLocation(program, "u_warp");
    const uIntensityLoc = gl.getUniformLocation(program, "u_intensity");
    const uAudioLowLoc = gl.getUniformLocation(program, "u_audioLow");
    const uAudioMidLoc = gl.getUniformLocation(program, "u_audioMid");
    const uAudioHighLoc = gl.getUniformLocation(program, "u_audioHigh");
    const uAudioLevelLoc = gl.getUniformLocation(program, "u_audioLevel");
    const uStatusModeLoc = gl.getUniformLocation(program, "u_statusMode");

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
    let currStatusMode = 0.0;
    const initialDialogActive = stateRef.current.isDialogActive;
    let currCenterX = (initialDialogActive && stateRef.current.showInAppAvatar) ? -0.08 : 0.0;
    let currCenterY = 0.95;

    let targetMouseX = 0.50;
    let targetMouseY = 0.50;
    let currMouseX = 0.50;
    let currMouseY = 0.50;

    let cachedRect = { left: 0, top: 0, width: 1, height: 1 };

    const handleMouseMove = (event: MouseEvent) => {
      if (cachedRect.width > 0 && cachedRect.height > 0) {
        targetMouseX = Math.max(0, Math.min(1, (event.clientX - cachedRect.left) / cachedRect.width));
        targetMouseY = Math.max(0, Math.min(1, 1.0 - (event.clientY - cachedRect.top) / cachedRect.height));
      }
    };

    window.addEventListener("mousemove", handleMouseMove, { passive: true });

    let lastTime = performance.now();
    let accumulatedTime = 0;
    resetTimeRef.current = () => {
      lastTime = performance.now();
    };

    const resize = (width?: number, height?: number) => {
      const clientW = width && width > 0 ? width : (canvas.clientWidth || window.innerWidth || 800);
      const clientH = height && height > 0 ? height : (canvas.clientHeight || window.innerHeight || 600);
      cachedRect = { left: 0, top: 0, width: clientW, height: clientH };

      // Atmospheric background portal is an ambient glow; capping at max 800x450 / DPR 0.8
      // drastically cuts GPU fragment shader fill-rate while preserving visual fidelity
      const dpr = Math.min(window.devicePixelRatio || 1, 0.8);

      let targetW = Math.max(1, Math.floor(clientW * dpr));
      let targetH = Math.max(1, Math.floor(clientH * dpr));

      const maxDim = 800;
      if (targetW > maxDim || targetH > maxDim) {
        const aspect = targetW / targetH;
        if (targetW >= targetH) {
          targetW = maxDim;
          targetH = Math.max(1, Math.floor(maxDim / aspect));
        } else {
          targetH = maxDim;
          targetW = Math.max(1, Math.floor(maxDim * aspect));
        }
      }

      if (Math.abs(canvas.width - targetW) > 2 || Math.abs(canvas.height - targetH) > 2) {
        canvas.width = targetW;
        canvas.height = targetH;
        gl.viewport(0, 0, targetW, targetH);
      }
    };

    const observer = typeof ResizeObserver !== "undefined"
      ? new ResizeObserver((entries) => {
          const entry = entries[0];
          if (entry?.contentRect && entry.contentRect.width > 0 && entry.contentRect.height > 0) {
            resize(entry.contentRect.width, entry.contentRect.height);
          } else {
            resize();
          }
        })
      : null;
    observer?.observe(canvas);
    resize();

    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);

    const render = (now: number) => {
      const state = stateRef.current;
      if (!state.isActive || (typeof document !== "undefined" && document.hidden)) {
        animationFrameRef.current = null;
        return;
      }

      const dt = Math.min(0.033, Math.max(0.001, (now - lastTime) / 1000));
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
      let targetStatus = 0.0; // 0=idle, 1=listening, 2=thinking, 3=speaking

      // Determine status target
      if (state.voiceState === "speaking") {
        targetStatus = 3.0;
        targetRadius = 0.58;
        targetSpeed *= 1.3;
        targetIntensity = 1.25;
      } else if (state.voiceState === "thinking" || state.voiceState === "transcribing" || state.loading) {
        targetStatus = 2.0;
        targetRadius = 0.54;
        targetSpeed *= 1.05;
        targetWarp = currentVisuals.warp;
        targetIntensity = 1.10;
      } else if (state.voiceState === "recording") {
        targetStatus = 1.0;
        targetRadius = 0.48;
        targetSpeed *= 1.4;
        targetIntensity = 1.15;
      } else if (state.voiceState === "error") {
        targetStatus = 4.0;
        targetRadius = 0.52;
        targetSpeed = 1.6;
        targetIntensity = 1.4;
        targetCoreLab = errorCoreLab;
        targetFringeLab = errorFringeLab;
        targetAccentLab = errorAccentLab;
      } else if (!state.isDialogActive) {
        targetStatus = 0.0;
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
      currStatusMode = lerp(currStatusMode, targetStatus, dynamicFactor);
      currCenterX = lerp(currCenterX, targetCenterX, dynamicFactor);
      currCenterY = lerp(currCenterY, targetCenterY, dynamicFactor);

      // Mouse smooth tracking
      currMouseX = lerp(currMouseX, targetMouseX, Math.min(1.0, dt * 6.0));
      currMouseY = lerp(currMouseY, targetMouseY, Math.min(1.0, dt * 6.0));

      accumulatedTime += dt * currSpeed;

      // Audio frequency spectrum from analyzer
      const bands = audioAnalyzer.getAudioBands();

      gl.uniform2f(uResLoc, canvas.width, canvas.height);
      gl.uniform1f(uTimeLoc, accumulatedTime);
      gl.uniform2f(uMouseLoc, currMouseX, currMouseY);
      gl.uniform2f(uCenterLoc, currCenterX, currCenterY);

      // Convert OKLab to sRGB only once per uniform upload
      const [rCore, gCore, bCore] = oklabToRgb(currCoreL, currCoreA, currCoreB);
      const [rFringe, gFringe, bFringe] = oklabToRgb(currFringeL, currFringeA, currFringeB);
      const [rAccent, gAccent, bAccent] = oklabToRgb(currAccentL, currAccentA, currAccentB);

      gl.uniform3f(uColorCoreLoc, rCore, gCore, bCore);
      gl.uniform3f(uColorFringeLoc, rFringe, gFringe, bFringe);
      gl.uniform3f(uColorAccentLoc, rAccent, gAccent, bAccent);

      gl.uniform1f(uRadiusLoc, currRadius);
      gl.uniform1f(uWarpLoc, currWarp);
      gl.uniform1f(uIntensityLoc, currIntensity);

      gl.uniform1f(uAudioLowLoc, bands.low);
      gl.uniform1f(uAudioMidLoc, bands.mid);
      gl.uniform1f(uAudioHighLoc, bands.high);
      gl.uniform1f(uAudioLevelLoc, bands.level);
      gl.uniform1f(uStatusModeLoc, currStatusMode);

      gl.drawArrays(gl.TRIANGLES, 0, 6);

      animationFrameRef.current = requestAnimationFrame(render);
    };

    renderCallbackRef.current = render;

    const handleVisibility = () => {
      if (document.hidden) {
        if (animationFrameRef.current !== null) {
          cancelAnimationFrame(animationFrameRef.current);
          animationFrameRef.current = null;
        }
      } else if (stateRef.current.isActive && animationFrameRef.current === null) {
        lastTime = performance.now();
        animationFrameRef.current = requestAnimationFrame(render);
      }
    };

    document.addEventListener("visibilitychange", handleVisibility);

    if (stateRef.current.isActive) {
      animationFrameRef.current = requestAnimationFrame(render);
    }

    return () => {
      document.removeEventListener("visibilitychange", handleVisibility);
      window.removeEventListener("mousemove", handleMouseMove);
      observer?.disconnect();
      if (animationFrameRef.current !== null) {
        cancelAnimationFrame(animationFrameRef.current);
        animationFrameRef.current = null;
      }
      renderCallbackRef.current = null;
      resetTimeRef.current = null;
      gl.deleteBuffer(positionBuffer);
      gl.deleteProgram(program);
    };
  }, []);

  return (
    <div className={`iris-portal-backdrop ${className}`.trim()} data-emotion={emotion} aria-hidden="true">
      <canvas ref={canvasRef} className="iris-portal-canvas" />
    </div>
  );
});

