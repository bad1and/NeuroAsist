// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { act, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { audioAnalyzer } from "../audio-analyzer";
import { IrisPortalBackground } from "./IrisPortalBackground";

const clock = vi.hoisted(() => ({
  tick: () => {},
  pause: vi.fn(), resume: vi.fn(), cancel: vi.fn(),
}));
vi.mock("animejs", () => ({
  createTimer: vi.fn((options: { onUpdate: () => void }) => {
    clock.tick = options.onUpdate;
    return clock;
  }),
}));

const paper = vi.hoisted(() => ({
  uniforms: vi.fn(), dispose: vi.fn(), mount: vi.fn(),
}));
vi.mock("@paper-design/shaders", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@paper-design/shaders")>();
  return {
    ...actual,
    getShaderNoiseTexture: () => undefined,
    ShaderMount: class {
      canvasElement: HTMLCanvasElement;
      constructor(host: HTMLElement, shader: string, uniforms: unknown, ...options: unknown[]) {
        this.canvasElement = document.createElement("canvas");
        host.append(this.canvasElement);
        paper.mount(shader, uniforms, ...options);
      }
      setUniforms = paper.uniforms;
      dispose = () => { paper.dispose(); this.canvasElement.remove(); };
    },
  };
});

afterEach(() => vi.restoreAllMocks());

describe("IrisPortalBackground", () => {
  it("renders canvas element inside backdrop container", () => {
    const { container } = render(
      <IrisPortalBackground
        emotion="neutral"
        voiceState="idle"
        loading={false}
        isDialogActive={false}
      />
    );

    const backdrop = container.querySelector(".iris-portal-backdrop");
    expect(backdrop).toBeInTheDocument();
    expect(backdrop?.querySelector(".iris-portal-canvas")).toBeInTheDocument();
  });

  it("updates smoothly when props change without throwing errors", () => {
    const { rerender, container } = render(
      <IrisPortalBackground
        emotion="joy"
        voiceState="speaking"
        loading={false}
        isDialogActive={true}
        showInAppAvatar={true}
      />
    );

    expect(container.querySelector(".iris-portal-canvas")).toBeInTheDocument();

    rerender(
      <IrisPortalBackground
        emotion="thinking"
        voiceState="thinking"
        loading={true}
        isDialogActive={true}
        showInAppAvatar={false}
      />
    );

    expect(container.querySelector(".iris-portal-canvas")).toBeInTheDocument();

    rerender(
      <IrisPortalBackground
        emotion="hurt"
        voiceState="error"
        loading={false}
        isDialogActive={true}
        showInAppAvatar={true}
      />
    );

    expect(container.querySelector(".iris-portal-canvas")).toBeInTheDocument();

    rerender(
      <IrisPortalBackground
        emotion="focused"
        voiceState="idle"
        loading={false}
        isDialogActive={false}
        showInAppAvatar={false}
      />
    );

    expect(container.querySelector(".iris-portal-canvas")).toBeInTheDocument();
  });
});

describe("portal rendering lifecycle", () => {
  function setupPaper() {
    paper.uniforms.mockClear(); paper.dispose.mockClear(); paper.mount.mockClear();
    clock.pause.mockClear(); clock.resume.mockClear(); clock.cancel.mockClear();
  }

  it("pauses inactive/hidden portals, resumes without rebuilding GL and disposes the timer", () => {
    setupPaper();
    const { rerender, unmount } = render(<IrisPortalBackground />);
    expect(clock.resume).toHaveBeenCalledTimes(1);
    expect(paper.mount).toHaveBeenCalledWith(expect.stringContaining("u_noiseTexture"),
      expect.objectContaining({ u_noise: 0.25, u_radius: 0.54, u_warp: 0.14, u_center: [0, 0.95] }),
      expect.any(Object), 0, 0, 2, 4_000_000);
    act(() => clock.tick());
    expect(paper.uniforms).toHaveBeenCalledTimes(1);
    rerender(<IrisPortalBackground isActive={false} />);
    expect(clock.pause).toHaveBeenCalled();
    act(() => clock.tick());
    expect(paper.uniforms).toHaveBeenCalledTimes(1);
    rerender(<IrisPortalBackground isActive />);
    expect(clock.resume).toHaveBeenCalledTimes(2);
    const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(true);
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    act(() => clock.tick());
    expect(paper.uniforms).toHaveBeenCalledTimes(1);
    hidden.mockReturnValue(false);
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    act(() => clock.tick());
    expect(paper.uniforms).toHaveBeenCalledTimes(2);
    unmount();
    expect(clock.cancel).toHaveBeenCalledTimes(1);
    expect(paper.dispose).toHaveBeenCalledTimes(1);
  });

  it("keeps playback bands reactive and resets the analyzer only when speech ends", () => {
    setupPaper();
    const reset = vi.spyOn(audioAnalyzer, "reset");
    vi.spyOn(audioAnalyzer, "getAudioBands").mockReturnValue({ low: 0.2, mid: 0.1, high: 0.05, level: 0.15 });
    const { rerender, unmount } = render(<IrisPortalBackground voiceState="speaking" />);
    act(() => clock.tick());
    expect(paper.uniforms).toHaveBeenLastCalledWith(expect.objectContaining({
      u_audioLow: expect.closeTo(0.155), u_radius: expect.any(Number),
    }));
    expect(paper.uniforms.mock.lastCall?.[0].u_radius).toBeGreaterThan(0.54);
    rerender(<IrisPortalBackground voiceState="idle" />);
    act(() => { clock.tick(); clock.tick(); });
    expect(reset).toHaveBeenCalledTimes(1);
    expect(paper.uniforms.mock.lastCall?.[0].u_audioLow).toBe(0);
    expect(paper.mount).toHaveBeenCalledTimes(1);
    unmount();
  });

  it("keeps Iris's three mood color roles and the wave center behind the avatar", () => {
    setupPaper();
    const { unmount } = render(<IrisPortalBackground emotion="joy" isDialogActive showInAppAvatar />);
    act(() => clock.tick());
    const uniforms = paper.uniforms.mock.lastCall?.[0];
    expect(uniforms.u_colorCore).toEqual([
      expect.closeTo(253 / 255), expect.closeTo(224 / 255), expect.closeTo(71 / 255),
    ]);
    expect(uniforms.u_colorFringe).toEqual([
      expect.closeTo(251 / 255), expect.closeTo(113 / 255), expect.closeTo(133 / 255),
    ]);
    expect(uniforms.u_colorAccent).toEqual([
      expect.closeTo(192 / 255), expect.closeTo(132 / 255), expect.closeTo(252 / 255),
    ]);
    expect(uniforms.u_center).toEqual([-0.08, 0.95]);
    unmount();
  });
});
