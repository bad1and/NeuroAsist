// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { act, cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { IrisMoodOrb } from "./IrisMoodOrb";

const clock = vi.hoisted(() => ({
  tick: () => {}, pause: vi.fn(), resume: vi.fn(), cancel: vi.fn(),
}));
vi.mock("animejs", () => ({ createTimer: vi.fn((options: { onUpdate: () => void }) => {
  clock.tick = options.onUpdate;
  return clock;
}) }));

function mockGL() {
  const gl = {
    createShader: vi.fn(() => ({})), shaderSource: vi.fn(), compileShader: vi.fn(),
    getShaderParameter: vi.fn(() => true), deleteShader: vi.fn(),
    createProgram: vi.fn(() => ({})), attachShader: vi.fn(), linkProgram: vi.fn(),
    getProgramParameter: vi.fn(() => true), deleteProgram: vi.fn(), useProgram: vi.fn(),
    createBuffer: vi.fn(() => ({})), bindBuffer: vi.fn(), bufferData: vi.fn(), deleteBuffer: vi.fn(),
    getAttribLocation: vi.fn(() => 0), enableVertexAttribArray: vi.fn(), vertexAttribPointer: vi.fn(),
    getUniformLocation: vi.fn((_program, name: string) => name),
    viewport: vi.fn(), uniform1f: vi.fn(), uniform2f: vi.fn(), uniform3f: vi.fn(), drawArrays: vi.fn(),
  };
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(gl as unknown as WebGLRenderingContext);
  return gl;
}

beforeEach(() => { clock.pause.mockClear(); clock.resume.mockClear(); clock.cancel.mockClear(); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("mood surface rendering", () => {
  it("changes mood and strength without rebuilding the context or canvas", () => {
    const gl = mockGL();
    let now = 1000;
    vi.spyOn(performance, "now").mockImplementation(() => now);
    const { container, rerender, unmount } = render(<IrisMoodOrb emotion="neutral" strength="muted" variant="surface" />);
    const canvas = container.querySelector("canvas");
    const firstPalette = gl.uniform3f.mock.calls.slice(-3);
    expect(gl.uniform1f).toHaveBeenCalledWith("u_surface", 1);
    expect(gl.uniform1f).toHaveBeenCalledWith("u_intensity", 0.65);
    rerender(<IrisMoodOrb emotion="anger" strength="strong" variant="surface" />);
    act(() => { now += 100; clock.tick(); });
    expect(container.querySelector("canvas")).toBe(canvas);
    expect(gl.createProgram).toHaveBeenCalledTimes(1);
    expect(gl.uniform3f.mock.calls.slice(-3)).not.toEqual(firstPalette);
    expect(gl.uniform1f.mock.calls.filter(([name]) => name === "u_intensity").slice(-1)[0]?.[1]).toBeGreaterThan(0.65);
    unmount();
    expect(clock.cancel).toHaveBeenCalledOnce();
    expect(gl.deleteBuffer).toHaveBeenCalledOnce();
    expect(gl.deleteProgram).toHaveBeenCalledOnce();
    expect(gl.deleteShader).toHaveBeenCalledTimes(2);
  });

  it("pauses hidden and offscreen cards, then resumes the same renderer", () => {
    const gl = mockGL();
    let intersect = (_visible: boolean) => {};
    const disconnect = vi.fn();
    vi.stubGlobal("IntersectionObserver", class {
      constructor(callback: IntersectionObserverCallback) {
        intersect = visible => callback([{ isIntersecting: visible } as IntersectionObserverEntry], this as unknown as IntersectionObserver);
      }
      observe() {}
      disconnect = disconnect;
    });
    const { unmount } = render(<IrisMoodOrb variant="surface" />);
    gl.drawArrays.mockClear();
    const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(true);
    act(() => { document.dispatchEvent(new Event("visibilitychange")); clock.tick(); });
    expect(gl.drawArrays).not.toHaveBeenCalled();
    hidden.mockReturnValue(false);
    act(() => { intersect(false); clock.tick(); });
    expect(gl.drawArrays).not.toHaveBeenCalled();
    act(() => { intersect(true); clock.tick(); });
    expect(gl.drawArrays).toHaveBeenCalledOnce();
    expect(clock.pause).toHaveBeenCalled();
    expect(gl.createProgram).toHaveBeenCalledTimes(1);
    unmount();
    expect(disconnect).toHaveBeenCalledOnce();
  });

  it("renders a still image for reduced motion and refreshes its palette on mood changes", () => {
    const gl = mockGL();
    vi.stubGlobal("matchMedia", () => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
    const { rerender } = render(<IrisMoodOrb emotion="neutral" variant="surface" />);
    expect(clock.resume).not.toHaveBeenCalled();
    gl.uniform3f.mockClear();
    rerender(<IrisMoodOrb emotion="joy" strength="noticeable" variant="surface" />);
    expect(gl.uniform3f).toHaveBeenCalledWith("u_colorCore", 253 / 255, 224 / 255, 71 / 255);
    expect(gl.uniform1f).toHaveBeenCalledWith("u_intensity", 1.15);
    expect(gl.uniform1f.mock.calls.filter(([name]) => name === "u_time").every(([, time]) => time === 0)).toBe(true);
  });

  it("retains a decorative colour wash when WebGL is unavailable", () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
    const { container } = render(<IrisMoodOrb emotion="joy" variant="surface" />);
    const surface = container.querySelector(".iris-mood-surface");
    expect(surface).toHaveAttribute("aria-hidden", "true");
    expect(surface).toHaveStyle({ "--mood-core": "#fde047" });
    expect(clock.resume).not.toHaveBeenCalled();
  });
});
