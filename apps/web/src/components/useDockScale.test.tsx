// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { renderHook, act } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { useRef } from "react";
import { useDockScale } from "./useDockScale";

describe("useDockScale", () => {
  let mockElement: HTMLDivElement;

  beforeEach(() => {
    mockElement = document.createElement("div");
    document.body.appendChild(mockElement);
  });

  afterEach(() => {
    if (mockElement && mockElement.parentNode) {
      mockElement.parentNode.removeChild(mockElement);
    }
    vi.restoreAllMocks();
  });

  it("возвращает масштаб 1 по умолчанию, если элемент не имеет размеров", () => {
    const { result } = renderHook(() => {
      const ref = useRef<HTMLDivElement | null>(mockElement);
      return useDockScale(ref);
    });

    expect(result.current).toBe(1);
  });

  it("корректно рассчитывает масштаб по ширине и устанавливает CSS-переменную", async () => {
    // Симулируем ширину 600px и высоту 800px (лимитирует ширина)
    // BASE_WIDTH = 829, MARGIN = 32 -> availWidth = 568 -> 568 / 829 ≈ 0.6852
    vi.spyOn(mockElement, "getBoundingClientRect").mockReturnValue({
      width: 600,
      height: 800,
      top: 0,
      bottom: 800,
      left: 0,
      right: 600,
      x: 0,
      y: 0,
      toJSON: () => {},
    });

    vi.spyOn(window, "requestAnimationFrame").mockImplementation((cb) => {
      cb(performance.now());
      return 1;
    });

    let hookResult: { current: number };
    await act(async () => {
      const { result } = renderHook(() => {
        const ref = useRef<HTMLDivElement | null>(mockElement);
        return useDockScale(ref);
      });
      hookResult = result;
    });

    expect(mockElement.style.getPropertyValue("--dock-scale")).toBe("0.6852");
    expect(mockElement.style.getPropertyValue("--panel-height")).toBe("800px");
    expect(hookResult!.current).toBeCloseTo(0.6852, 3);
  });

  it("учитывает ограничение по высоте (не более ~32% высоты панели)", async () => {
    // Симулируем широкое, но очень низкое окно: ширина 1200px, высота 400px
    // scaleW = (1200 - 32) / 829 = 1.408
    // scaleH = (400 * 0.32) / 183.5 = 128 / 183.5 ≈ 0.6975
    // min(scaleW, scaleH) = 0.6975
    vi.spyOn(mockElement, "getBoundingClientRect").mockReturnValue({
      width: 1200,
      height: 400,
      top: 0,
      bottom: 400,
      left: 0,
      right: 1200,
      x: 0,
      y: 0,
      toJSON: () => {},
    });

    vi.spyOn(window, "requestAnimationFrame").mockImplementation((cb) => {
      cb(performance.now());
      return 1;
    });

    let hookResult: { current: number };
    await act(async () => {
      const { result } = renderHook(() => {
        const ref = useRef<HTMLDivElement | null>(mockElement);
        return useDockScale(ref);
      });
      hookResult = result;
    });

    expect(mockElement.style.getPropertyValue("--dock-scale")).toBe("0.6975");
    expect(hookResult!.current).toBeCloseTo(0.6975, 3);
  });

  it("ограничивает масштаб минимальным (0.55) и максимальным (1.20) порогами", async () => {
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((cb) => {
      cb(performance.now());
      return 1;
    });

    // Слишком маленький размер: ширина 200px -> scaleW < 0.55
    vi.spyOn(mockElement, "getBoundingClientRect").mockReturnValue({
      width: 200,
      height: 200,
      top: 0,
      bottom: 200,
      left: 0,
      right: 200,
      x: 0,
      y: 0,
      toJSON: () => {},
    });

    let hookResult: { current: number };
    await act(async () => {
      const { result } = renderHook(() => {
        const ref = useRef<HTMLDivElement | null>(mockElement);
        return useDockScale(ref);
      });
      hookResult = result;
    });

    expect(mockElement.style.getPropertyValue("--dock-scale")).toBe("0.55");
    expect(hookResult!.current).toBe(0.55);

    // Слишком большой размер: ширина 3840px (4K) -> scaleW > 1.20
    vi.spyOn(mockElement, "getBoundingClientRect").mockReturnValue({
      width: 3840,
      height: 2160,
      top: 0,
      bottom: 2160,
      left: 0,
      right: 3840,
      x: 0,
      y: 0,
      toJSON: () => {},
    });

    // Trigger resize
    await act(async () => {
      window.dispatchEvent(new Event("resize"));
    });

    expect(mockElement.style.getPropertyValue("--dock-scale")).toBe("1.2");
  });
});
