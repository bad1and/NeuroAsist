// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { materialGeometryRevision, observeMaterialSize, subscribeMaterialGeometry } from "./materialLayout";

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("uses one scroll listener for many controls and removes it when the last leaves", () => {
  const add = vi.spyOn(window, "addEventListener");
  const remove = vi.spyOn(window, "removeEventListener");
  const cleanup = Array.from({ length: 100 }, () => subscribeMaterialGeometry());
  expect(add.mock.calls.filter(call => call[0] === "scroll")).toHaveLength(1);
  const before = materialGeometryRevision();
  window.dispatchEvent(new Event("scroll"));
  expect(materialGeometryRevision()).toBe(before + 1);
  cleanup.slice(0, 99).forEach(stop => stop());
  expect(remove.mock.calls.filter(call => call[0] === "scroll")).toHaveLength(0);
  cleanup[99]();
  expect(remove.mock.calls.filter(call => call[0] === "scroll")).toHaveLength(1);
});

it("batches size delivery through one observer and releases detached controls", () => {
  const observe = vi.fn(), unobserve = vi.fn(), disconnect = vi.fn();
  let deliver!: (entries: ResizeObserverEntry[]) => void;
  const constructor = vi.fn(function (callback: typeof deliver) { deliver = callback; return { observe, unobserve, disconnect }; });
  vi.stubGlobal("ResizeObserver", constructor);
  const a = document.createElement("button"), b = document.createElement("button");
  const sizeA = vi.fn(), sizeB = vi.fn();
  const stopA = observeMaterialSize(a, sizeA), stopB = observeMaterialSize(b, sizeB);
  expect(constructor).toHaveBeenCalledOnce();
  deliver([{ target: a, borderBoxSize: [{ inlineSize: 100, blockSize: 44 }] }, { target: b, borderBoxSize: [{ inlineSize: 200, blockSize: 44 }] }] as unknown as ResizeObserverEntry[]);
  expect(sizeA).toHaveBeenCalledWith(100, 44);
  expect(sizeB).toHaveBeenCalledWith(200, 44);
  stopA();
  expect(disconnect).not.toHaveBeenCalled();
  deliver([{ target: a, borderBoxSize: [{ inlineSize: 120, blockSize: 44 }] }] as unknown as ResizeObserverEntry[]);
  expect(sizeA).toHaveBeenCalledTimes(1);
  stopB();
  expect(unobserve).toHaveBeenCalledTimes(2);
  expect(disconnect).toHaveBeenCalledOnce();
});
