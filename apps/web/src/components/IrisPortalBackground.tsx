import { useEffect, useRef } from "react";
import { getMoodVisuals } from "../mood-visuals";
import { audioAnalyzer } from "../audio-analyzer";
import type { VoiceState } from "../types";

export interface IrisPortalBackgroundProps {
  emotion?: string;
  voiceState?: VoiceState;
  loading?: boolean;
  isDialogActive?: boolean;
  showInAppAvatar?: boolean;
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
  return [0.75, 0.52, 0.98]; // Default lilac
}

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

function lerp3(a: [number, number, number], b: [number, number, number], t: number): [number, number, number] {
  return [lerp(a[0], b[0], t), lerp(a[1], b[1], t), lerp(a[2], b[2], t)];
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
    p.y += sin(p.x * 2.4 + u_time * 0.45) * warp;
    p.x += noise(p * 1.8 + u_time * 0.2) * (warp * 0.85);
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
    float wash = smoothstep(dynRadius * 2.2, 0.0, distToCenter) * 0.20;

    // Thinking ripple pulsation
    float thinkingPulse = 0.0;
    if (u_statusMode > 1.5 && u_statusMode < 2.5) {
        float ringWave = sin(distToCenter * 18.0 - u_time * 4.5);
        thinkingPulse = smoothstep(0.72, 1.0, ringWave) * 0.18;
    }

    // Glow distributions
    float coreGlow = exp(-d1 * (26.0 - u_audioHigh * 7.0));
    float fringeGlow = exp(-d2 * 8.8);

    vec3 finalColor = vec3(0.0);
    finalColor += u_colorCore * (coreGlow * (1.30 + u_audioHigh * 0.65));
    finalColor += u_colorFringe * (fringeGlow * (1.10 + u_audioMid * 0.45));
    finalColor += u_colorAccent * ((wash + thinkingPulse) * (0.85 + u_audioLevel * 0.5));
    finalColor += u_colorFringe * wash * (sin(u_time * 0.65) * 0.25 + 0.75);

    float alpha = clamp((coreGlow * 1.5 + fringeGlow * 0.95 + wash * 0.75 + thinkingPulse), 0.0, 1.0);
    vec3 toneMapped = vec3(1.0) - exp(-finalColor * (1.6 * dynIntensity));

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

export function IrisPortalBackground({
  emotion = "neutral",
  voiceState = "idle",
  loading = false,
  isDialogActive = false,
  showInAppAvatar = false,
  className = "",
}: IrisPortalBackgroundProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const animationFrameRef = useRef<number | null>(null);

  // References for live smooth interpolation without re-binding WebGL
  const stateRef = useRef({
    emotion,
    voiceState,
    loading,
    isDialogActive,
    showInAppAvatar,
  });

  useEffect(() => {
    stateRef.current = {
      emotion,
      voiceState,
      loading,
      isDialogActive,
      showInAppAvatar,
    };
  }, [emotion, voiceState, loading, isDialogActive, showInAppAvatar]);

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

    // Live state values for smooth lerping
    const visuals = getMoodVisuals(emotion);
    let currCore = hexToRgb(visuals.colors[0]);
    let currFringe = hexToRgb(visuals.colors[1]);
    let currAccent = hexToRgb(visuals.colors[2]);
    let currWarp = visuals.warp;
    let currSpeed = visuals.speed;
    let currRadius = 0.54;
    let currIntensity = 1.0;
    let currStatusMode = 0.0;
    let currCenterX = -0.08;
    let currCenterY = 0.95;

    let targetMouseX = 0.50;
    let targetMouseY = 0.50;
    let currMouseX = 0.50;
    let currMouseY = 0.50;

    const handleMouseMove = (event: MouseEvent) => {
      const rect = canvas.getBoundingClientRect();
      if (rect.width > 0 && rect.height > 0) {
        targetMouseX = (event.clientX - rect.left) / rect.width;
        targetMouseY = 1.0 - (event.clientY - rect.top) / rect.height;
      }
    };

    window.addEventListener("mousemove", handleMouseMove, { passive: true });

    let lastTime = performance.now();
    let accumulatedTime = 0;

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const displayWidth = Math.max(1, Math.floor(canvas.clientWidth * dpr));
      const displayHeight = Math.max(1, Math.floor(canvas.clientHeight * dpr));

      if (canvas.width !== displayWidth || canvas.height !== displayHeight) {
        canvas.width = displayWidth;
        canvas.height = displayHeight;
        gl.viewport(0, 0, canvas.width, canvas.height);
      }
    };

    const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(resize) : null;
    observer?.observe(canvas);
    resize();

    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);

    const render = (now: number) => {
      const dt = Math.min(0.1, (now - lastTime) / 1000);
      lastTime = now;

      const state = stateRef.current;
      const currentVisuals = getMoodVisuals(state.emotion);

      let targetCore = hexToRgb(currentVisuals.colors[0]);
      let targetFringe = hexToRgb(currentVisuals.colors[1]);
      let targetAccent = hexToRgb(currentVisuals.colors[2]);
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
        targetRadius = 0.50;
        targetSpeed *= 2.2;
        targetWarp *= 1.3;
        targetIntensity = 1.35;
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
        targetCore = [1.0, 0.35, 0.35];
        targetFringe = [0.85, 0.15, 0.15];
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

      // Smooth interpolation (lerp)
      const lerpFactor = Math.min(1.0, dt * 4.5);
      currCore = lerp3(currCore, targetCore, lerpFactor);
      currFringe = lerp3(currFringe, targetFringe, lerpFactor);
      currAccent = lerp3(currAccent, targetAccent, lerpFactor);
      currWarp = lerp(currWarp, targetWarp, lerpFactor);
      currSpeed = lerp(currSpeed, targetSpeed, lerpFactor);
      currRadius = lerp(currRadius, targetRadius, lerpFactor);
      currIntensity = lerp(currIntensity, targetIntensity, lerpFactor);
      currStatusMode = lerp(currStatusMode, targetStatus, lerpFactor);
      currCenterX = lerp(currCenterX, targetCenterX, lerpFactor);
      currCenterY = lerp(currCenterY, targetCenterY, lerpFactor);

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

      gl.uniform3f(uColorCoreLoc, currCore[0], currCore[1], currCore[2]);
      gl.uniform3f(uColorFringeLoc, currFringe[0], currFringe[1], currFringe[2]);
      gl.uniform3f(uColorAccentLoc, currAccent[0], currAccent[1], currAccent[2]);

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

    animationFrameRef.current = requestAnimationFrame(render);

    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      observer?.disconnect();
      if (animationFrameRef.current !== null) {
        cancelAnimationFrame(animationFrameRef.current);
      }
      gl.deleteBuffer(positionBuffer);
      gl.deleteProgram(program);
    };
  }, []);

  return (
    <div className={`iris-portal-backdrop ${className}`} aria-hidden="true">
      <canvas ref={canvasRef} className="iris-portal-canvas" />
    </div>
  );
}
