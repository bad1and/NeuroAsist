import { useEffect, useRef, type CSSProperties } from "react";
import { createTimer } from "animejs";
import { getMoodVisuals } from "../mood-visuals";

export interface IrisMoodOrbProps {
  emotion?: string;
  strength?: string;
  className?: string;
  size?: number;
  variant?: "orb" | "surface";
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

function lerpOklab(
  c1: [number, number, number],
  c2: [number, number, number],
  t: number
): [number, number, number] {
  if (t <= 0) return c1;
  if (t >= 1) return c2;
  const lab1 = rgbToOklab(c1[0], c1[1], c1[2]);
  const lab2 = rgbToOklab(c2[0], c2[1], c2[2]);
  const L = lab1[0] + (lab2[0] - lab1[0]) * t;
  const a = lab1[1] + (lab2[1] - lab1[1]) * t;
  const b = lab1[2] + (lab2[2] - lab1[2]) * t;
  return oklabToRgb(L, a, b);
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
uniform vec2 u_center;

uniform vec3 u_colorCore;
uniform vec3 u_colorFringe;
uniform vec3 u_colorAccent;

uniform float u_radius;
uniform float u_warp;
uniform float u_intensity;
uniform float u_surface;

vec2 hash( vec2 p ) {
    p = vec2( dot(p,vec2(127.1,311.7)), dot(p,vec2(269.5,183.3)) );
    return -1.0 + 2.0*fract(sin(p)*43758.5453123);
}

float noise( in vec2 p ) {
    const float K1 = 0.366025404;
    const float K2 = 0.211324865;
    vec2 i = floor( p + (p.x+p.y)*K1 );
    vec2 a = p - i + (i.x+i.y)*K2;
    vec2 o = (a.x>a.y) ? vec2(1.0,0.0) : vec2(0.0,1.0);
    vec2 b = a - o + K2;
    vec2 c = a - 1.0 + 2.0*K2;
    vec3 h = max( 0.5-vec3(dot(a,a), dot(b,b), dot(c,c) ), 0.0 );
    vec3 n = h*h*h*h*vec3( dot(a,hash(i+0.0)), dot(b,hash(i+o)), dot(c,hash(i+1.0)));
    return dot( n, vec3(70.0) );
}

float sdArc(vec2 p, vec2 center, float radius, float width, float warp) {
    p.y += sin(p.x * 2.8 + u_time * 0.6) * warp;
    p.x += noise(p * 2.2 + u_time * 0.3) * (warp * 0.85);
    float d = length(p - center) - radius;
    return abs(d) - width;
}

void main() {
    vec2 uv = gl_FragCoord.xy / u_resolution.xy;
    if (u_surface > 0.5) {
        // A broad, off-centre liquid orbit: the card is the viewport, not a
        // scaled-up square icon. All distances are normalised to the card.
        float t = u_time * 0.48;
        vec2 p = (uv - vec2(0.70, 0.55)) / vec2(0.63, 0.76);
        float agitation = u_warp * (0.65 + u_intensity * 0.35);
        p.x += sin(p.y * 2.8 + t * 0.7) * agitation * 0.42;
        p.y += noise(p * 1.5 + vec2(t * 0.23, -t * 0.17)) * agitation;
        float angle = atan(p.y, p.x);
        float radius = length(p);
        float breath = sin(t * 0.9) * 0.035 * u_intensity;
        float wave = sin(angle * 3.0 + t) * agitation * 0.20;
        float orbit = radius - (0.84 + breath + wave);
        float fold = orbit + 0.16 + sin(angle * 2.0 - t * 0.6) * 0.065;
        // Broad pigment planes, with no bright centre line or specular rim.
        // The orbit still drives the movement, but now carries actual colour.
        float plane = 1.0 - smoothstep(0.08, 0.52, abs(orbit + 0.04));
        float echo = 1.0 - smoothstep(0.05, 0.32, abs(fold));
        float atmosphere = exp(-abs(orbit) * 2.4);
        float flow = 0.5 + 0.5 * sin(angle * 2.0 - t * 0.65 + radius * 2.0);
        vec3 ribbon = mix(u_colorFringe, u_colorCore, flow);
        ribbon = mix(ribbon, u_colorAccent, (0.5 + 0.5 * sin(angle * 3.0 + t * 0.4)) * 0.48);
        vec3 pigment = mix(ribbon, mix(u_colorAccent, u_colorFringe, flow), echo * 0.36);
        // A quiet colour wash links both edges; the left remains readable.
        float mist = exp(-length((uv - vec2(0.45, 0.48)) * vec2(1.2, 2.0)) * 2.0);
        float grain = fract(sin(dot(gl_FragCoord.xy, vec2(12.9898, 78.233))) * 43758.5453);
        pigment *= 0.80 + grain * 0.12;
        float veil = mix(0.38, 1.0, smoothstep(0.05, 0.70, uv.x));
        float coverage = clamp(plane * 0.66 + echo * 0.18 + atmosphere * 0.12 + mist * 0.10, 0.0, 1.0);
        // Fine static grain breaks up the pigment, as on the dialogue portal.
        float alpha = clamp((coverage + (grain - 0.5) * 0.10 * coverage) * veil * u_intensity, 0.0, 0.82);
        gl_FragColor = vec4(pigment, alpha);
        return;
    }
    vec2 st = uv;
    float aspect = u_resolution.x / u_resolution.y;
    st.x *= aspect;

    vec2 center = u_center;
    center.x *= aspect;

    // Organic breathing pulsation
    float dynRadius = u_radius + sin(u_time * 1.2) * 0.015;
    float dynWarp = u_warp;
    float dynIntensity = u_intensity;

    // Dual organic arcs
    float d1 = sdArc(st, center, dynRadius, 0.024, dynWarp);
    float d2 = sdArc(st, center, dynRadius + 0.045, 0.05, dynWarp * 1.3);

    float distToCenter = length(st - center);
    float wash = smoothstep(dynRadius * 1.9, 0.0, distToCenter) * 0.35;

    // Glow distributions
    float coreGlow = exp(-d1 * 24.0);
    float fringeGlow = exp(-d2 * 8.5);

    // Subtle multi-spectral dispersion along the arc
    float angle = atan(st.y - center.y, st.x - center.x);
    float spectralMod = sin(angle * 3.0 + u_time * 0.6) * 0.12 + 0.88;

    // Signature iris violet undertone for brand cohesion
    vec3 irisBaseViolet = vec3(0.412, 0.357, 0.525);

    vec3 finalColor = vec3(0.0);
    finalColor += u_colorCore * (coreGlow * 1.45);
    finalColor += mix(u_colorFringe, u_colorCore, 0.25 * spectralMod) * (fringeGlow * 1.25);
    finalColor += u_colorAccent * (wash * 0.95);
    finalColor += mix(u_colorFringe, irisBaseViolet, 0.22) * wash * (sin(u_time * 0.8) * 0.20 + 0.80);

    // Soft radial falloff towards edges so glow dissipates seamlessly without any visible borders
    float edgeFalloff = smoothstep(0.49, 0.35, distToCenter);
    finalColor *= edgeFalloff;

    float alpha = clamp((coreGlow * 1.6 + fringeGlow * 1.0 + wash * 0.9), 0.0, 1.0) * edgeFalloff;
    vec3 toneMapped = vec3(1.0) - exp(-finalColor * (1.7 * dynIntensity));

    gl_FragColor = vec4(toneMapped, alpha);
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

function createProgram(
  gl: WebGLRenderingContext,
  vertexSource: string,
  fragmentSource: string
): WebGLProgram | null {
  const vertexShader = createShader(gl, gl.VERTEX_SHADER, vertexSource);
  const fragmentShader = createShader(gl, gl.FRAGMENT_SHADER, fragmentSource);
  if (!vertexShader || !fragmentShader) {
    if (vertexShader) gl.deleteShader(vertexShader);
    if (fragmentShader) gl.deleteShader(fragmentShader);
    return null;
  }

  const program = gl.createProgram();
  if (!program) {
    gl.deleteShader(vertexShader);
    gl.deleteShader(fragmentShader);
    return null;
  }
  gl.attachShader(program, vertexShader);
  gl.attachShader(program, fragmentShader);
  gl.linkProgram(program);
  gl.deleteShader(vertexShader);
  gl.deleteShader(fragmentShader);

  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    gl.deleteProgram(program);
    return null;
  }
  return program;
}

export function IrisMoodOrb({
  emotion = "neutral",
  strength = "medium",
  className = "",
  size = 80,
  variant = "orb",
}: IrisMoodOrbProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const redrawRef = useRef<(() => void) | null>(null);

  const stateRef = useRef({ emotion, strength, variant });

  useEffect(() => {
    stateRef.current = { emotion, strength, variant };
    redrawRef.current?.();
  }, [emotion, strength, variant]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;

    let gl: WebGLRenderingContext | null = null;
    try {
      gl = canvas.getContext("webgl", {
        alpha: true,
        antialias: false,
        depth: false,
        stencil: false,
        premultipliedAlpha: false,
        powerPreference: "low-power",
      });
    } catch {
      return undefined;
    }
    if (!gl) return undefined;

    const program = createProgram(gl, VERTEX_SHADER_SOURCE, FRAGMENT_SHADER_SOURCE);
    if (!program) return undefined;

    gl.useProgram(program);

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

    const uResLoc = gl.getUniformLocation(program, "u_resolution");
    const uTimeLoc = gl.getUniformLocation(program, "u_time");
    const uCenterLoc = gl.getUniformLocation(program, "u_center");
    const uColorCoreLoc = gl.getUniformLocation(program, "u_colorCore");
    const uColorFringeLoc = gl.getUniformLocation(program, "u_colorFringe");
    const uColorAccentLoc = gl.getUniformLocation(program, "u_colorAccent");
    const uRadiusLoc = gl.getUniformLocation(program, "u_radius");
    const uWarpLoc = gl.getUniformLocation(program, "u_warp");
    const uIntensityLoc = gl.getUniformLocation(program, "u_intensity");
    const uSurfaceLoc = gl.getUniformLocation(program, "u_surface");

    const visuals = getMoodVisuals(emotion);
    let currCore = hexToRgb(visuals.colors[0]);
    let currFringe = hexToRgb(visuals.colors[1]);
    let currAccent = hexToRgb(visuals.colors[2]);
    let currWarp = visuals.warp;
    let currSpeed = visuals.speed;
    const currRadius = 0.28;
    let currIntensity = 1.0;

    let lastTime = performance.now();
    let accumulatedTime = 0;
    let visible = true;
    let contextLost = false;
    const motion = window.matchMedia?.("(prefers-reduced-motion: reduce)");

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
      const displayWidth = Math.max(1, Math.floor(canvas.clientWidth * dpr));
      const displayHeight = Math.max(1, Math.floor(canvas.clientHeight * dpr));

      if (canvas.width !== displayWidth || canvas.height !== displayHeight) {
        canvas.width = displayWidth;
        canvas.height = displayHeight;
        gl.viewport(0, 0, canvas.width, canvas.height);
      }
    };

    // The shader returns straight alpha. Let the browser composite it once;
    // blending into the transparent buffer would apply its alpha twice.
    const render = (now: number, immediate = false) => {
      if (document.hidden || !visible || contextLost) return;
      const dt = immediate ? 0 : Math.min(0.1, (now - lastTime) / 1000);
      lastTime = now;

      const state = stateRef.current;
      const currentVisuals = getMoodVisuals(state.emotion);

      const targetCore = hexToRgb(currentVisuals.colors[0]);
      const targetFringe = hexToRgb(currentVisuals.colors[1]);
      const targetAccent = hexToRgb(currentVisuals.colors[2]);
      const targetWarp = currentVisuals.warp;
      const targetSpeed = currentVisuals.speed;
      const targetIntensity = ({
        muted: 0.65, subtle: 0.78, low: 0.78, moderate: 1, medium: 1,
        noticeable: 1.15, high: 1.25, strong: 1.3, intense: 1.45,
      } as Record<string, number>)[state.strength] ?? 1;

      const fringeFactor = immediate ? 1 : Math.min(1.0, dt * 5.4);
      currFringe = lerpOklab(currFringe, targetFringe, fringeFactor);

      const coreFactor = immediate ? 1 : Math.min(1.0, dt * 3.8);
      currCore = lerpOklab(currCore, targetCore, coreFactor);

      const accentFactor = immediate ? 1 : Math.min(1.0, dt * 2.4);
      currAccent = lerpOklab(currAccent, targetAccent, accentFactor);

      const dynamicFactor = immediate ? 1 : Math.min(1.0, dt * 4.2);
      currWarp = lerp(currWarp, targetWarp, dynamicFactor);
      currSpeed = lerp(currSpeed, targetSpeed, dynamicFactor);
      currIntensity = lerp(currIntensity, targetIntensity, dynamicFactor);

      if (!motion?.matches) accumulatedTime += dt * currSpeed * (0.7 + currIntensity * 0.3);

      gl.uniform2f(uResLoc, canvas.width, canvas.height);
      gl.uniform1f(uTimeLoc, accumulatedTime);
      gl.uniform2f(uCenterLoc, 0.5, 0.5);

      gl.uniform3f(uColorCoreLoc, currCore[0], currCore[1], currCore[2]);
      gl.uniform3f(uColorFringeLoc, currFringe[0], currFringe[1], currFringe[2]);
      gl.uniform3f(uColorAccentLoc, currAccent[0], currAccent[1], currAccent[2]);

      gl.uniform1f(uRadiusLoc, currRadius);
      gl.uniform1f(uWarpLoc, currWarp);
      gl.uniform1f(uIntensityLoc, currIntensity);
      gl.uniform1f(uSurfaceLoc, state.variant === "surface" ? 1 : 0);

      gl.drawArrays(gl.TRIANGLES, 0, 6);
    };

    const timer = createTimer({
      loop: true, frameRate: 30, autoplay: false,
      onUpdate: () => render(performance.now()),
    });
    const syncPlayback = () => {
      lastTime = performance.now();
      if (document.hidden || !visible || contextLost) {
        timer.pause();
      } else if (motion?.matches) {
        timer.pause();
        render(lastTime, true);
      } else {
        timer.resume();
      }
    };
    redrawRef.current = () => {
      if (motion?.matches) render(performance.now(), true);
    };
    const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(() => {
      resize();
      render(performance.now(), Boolean(motion?.matches));
    }) : null;
    observer?.observe(canvas);
    const intersection = typeof IntersectionObserver !== "undefined" ? new IntersectionObserver(entries => {
      visible = entries[0]?.isIntersecting ?? true;
      syncPlayback();
    }) : null;
    intersection?.observe(canvas);
    const onContextLost = () => { contextLost = true; timer.pause(); };
    canvas.addEventListener("webglcontextlost", onContextLost);
    document.addEventListener("visibilitychange", syncPlayback);
    motion?.addEventListener("change", syncPlayback);
    resize();
    render(performance.now(), true);
    syncPlayback();

    return () => {
      redrawRef.current = null;
      observer?.disconnect();
      intersection?.disconnect();
      document.removeEventListener("visibilitychange", syncPlayback);
      motion?.removeEventListener("change", syncPlayback);
      canvas.removeEventListener("webglcontextlost", onContextLost);
      timer.cancel();
      gl.deleteBuffer(positionBuffer);
      gl.deleteProgram(program);
    };
  }, []);

  return (
    <div
      className={`iris-mood-orb-container ${variant === "surface" ? "iris-mood-surface" : ""} ${className}`.trim()}
      style={{
        ...(variant === "orb" ? { width: size, height: size } : {}),
        "--mood-core": getMoodVisuals(emotion).colors[0],
        "--mood-fringe": getMoodVisuals(emotion).colors[1],
        "--mood-accent": getMoodVisuals(emotion).colors[2],
      } as CSSProperties}
      aria-hidden="true"
    >
      <canvas ref={canvasRef} className="iris-mood-orb-canvas" />
    </div>
  );
}
