// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { installScrollEdgeFades } from "./ScrollEdgeFades";
import { observeScrollEdgeFade } from "./useScrollEdgeFade";

let frames: Map<number, FrameRequestCallback>;
let nextFrame: number;
let disposers: Array<() => void>;
let resizeCallbacks: Array<ResizeObserverCallback>;

beforeEach(() => {
  frames = new Map(); nextFrame = 0; disposers = []; resizeCallbacks = [];
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => { frames.set(++nextFrame, callback); return nextFrame; });
  vi.stubGlobal("cancelAnimationFrame", (id: number) => frames.delete(id));
  vi.stubGlobal("ResizeObserver", class {
    constructor(callback: ResizeObserverCallback) { resizeCallbacks.push(callback); }
    observe() {} disconnect() {}
  });
});
afterEach(() => { disposers.forEach(dispose => dispose()); document.body.replaceChildren(); vi.unstubAllGlobals(); });

async function flush() {
  await Promise.resolve();
  for (const [id, callback] of [...frames]) { frames.delete(id); callback(0); }
  await Promise.resolve();
}

function viewport(className: string, height = 300, contentHeight = 900) {
  const node = document.createElement("div");
  node.className = className;
  node.style.overflowY = "auto";
  Object.defineProperties(node, {
    clientHeight: { configurable: true, value: height },
    scrollHeight: { configurable: true, value: contentHeight },
  });
  return node;
}
function fade(node: HTMLElement) {
  return [node.style.getPropertyValue("--scroll-fade-top"), node.style.getPropertyValue("--scroll-fade-bottom")];
}

describe("shared scroll edge fades", () => {
  it("keeps nested history scrolling independent and reveals the first/last rows", async () => {
    const page = viewport("workspace");
    const messages = viewport("journal-messages-container");
    page.append(messages); document.body.append(page);
    disposers.push(installScrollEdgeFades(document.body));
    expect(fade(page)).toEqual(["0px", "64px"]);
    expect(fade(messages)).toEqual(["0px", "64px"]);
    messages.scrollTop = 100;
    messages.dispatchEvent(new Event("scroll")); await flush();
    expect(fade(messages)).toEqual(["48px", "64px"]);
    expect(fade(page)).toEqual(["0px", "64px"]);
    messages.scrollTop = 600;
    messages.dispatchEvent(new Event("scroll")); await flush();
    expect(fade(messages)).toEqual(["48px", "0px"]);
  });

  it("discovers newly opened portal lists and cleans up removed routes", async () => {
    disposers.push(installScrollEdgeFades(document.body));
    const list = viewport("spotlight-results-area");
    document.body.append(list); await flush();
    expect(list.hasAttribute("data-scroll-edge-fade")).toBe(true);
    list.remove(); await flush();
    expect(list.hasAttribute("data-scroll-edge-fade")).toBe(false);
    expect(fade(list)).toEqual(["", ""]);
  });

  it("recomputes after nested text changes, disclosure replacement, image load and resize", async () => {
    const list = viewport("memory-context-details", 300, 100);
    const nested = document.createElement("section");
    nested.innerHTML = "<p>Short</p>"; list.append(nested); document.body.append(list);
    disposers.push(installScrollEdgeFades(document.body));
    expect(list.hasAttribute("data-scroll-edge-fade")).toBe(false);
    Object.defineProperty(list, "scrollHeight", { configurable: true, value: 800 });
    nested.querySelector("p")!.firstChild!.textContent = "A longer memory";
    await flush(); expect(fade(list)).toEqual(["0px", "64px"]);
    Object.defineProperty(list, "scrollHeight", { configurable: true, value: 100 });
    nested.replaceChildren(document.createElement("img"));
    await flush(); expect(list.hasAttribute("data-scroll-edge-fade")).toBe(false);
    Object.defineProperty(list, "scrollHeight", { configurable: true, value: 800 });
    nested.firstElementChild!.dispatchEvent(new Event("load"));
    await flush(); expect(list.hasAttribute("data-scroll-edge-fade")).toBe(true);
    Object.defineProperty(list, "clientHeight", { configurable: true, value: 900 });
    resizeCallbacks.forEach(callback => callback([], {} as ResizeObserver));
    await flush(); expect(list.hasAttribute("data-scroll-edge-fade")).toBe(false);
  });

  it("preserves fixed shells and fields, then enables the responsive scroll viewport", async () => {
    const shell = viewport("workspace"); shell.style.overflowY = "hidden";
    const surface = viewport("memory-card");
    const input = document.createElement("textarea");
    shell.append(surface, input); document.body.append(shell);
    disposers.push(installScrollEdgeFades(document.body));
    expect(shell.hasAttribute("data-scroll-edge-fade")).toBe(false);
    expect(surface.style.getPropertyValue("--scroll-fade-top")).toBe("");
    expect(input.hasAttribute("data-scroll-edge-fade")).toBe(false);
    shell.style.overflowY = "auto";
    window.dispatchEvent(new Event("resize")); await flush();
    expect(shell.hasAttribute("data-scroll-edge-fade")).toBe(true);
    expect(fade(shell)).toEqual(["0px", "64px"]);
  });

  it("includes inline preparation logs without masking short code blocks", () => {
    const log = document.createElement("pre"); log.style.overflowY = "auto";
    Object.defineProperties(log, { clientHeight: { value: 200 }, scrollHeight: { value: 800 } });
    const short = document.createElement("pre"); short.textContent = "Short code";
    document.body.append(log, short);
    disposers.push(installScrollEdgeFades(document.body));
    expect(log.hasAttribute("data-scroll-edge-fade")).toBe(true);
    expect(short.hasAttribute("data-scroll-edge-fade")).toBe(false);
  });

  it("shares one observer with explicit hooks and cancels pending work on final cleanup", async () => {
    const list = viewport("settings-content"); document.body.append(list);
    const stopHook = observeScrollEdgeFade(list);
    const stopRegistry = installScrollEdgeFades(document.body);
    stopHook();
    expect(list.hasAttribute("data-scroll-edge-fade")).toBe(true);
    list.dispatchEvent(new Event("scroll"));
    expect(frames.size).toBeGreaterThan(0);
    stopRegistry(); await flush();
    expect(frames.size).toBe(0);
    expect(fade(list)).toEqual(["", ""]);
    expect(list.hasAttribute("data-scroll-edge-fade")).toBe(false);
  });
});
