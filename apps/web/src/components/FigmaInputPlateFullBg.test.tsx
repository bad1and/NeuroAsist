// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FigmaDockBg, FigmaInputPlateFullBg, FigmaSquareButtonBg } from "../FigmaIcons";

describe("FigmaInputPlateFullBg", () => {
  it("рендерит базовую SVG подложку с extraHeight = 0 без искажений", () => {
    const { container } = render(<FigmaInputPlateFullBg data-testid="plate" />);
    const svg = container.querySelector("svg");
    expect(svg).toBeInTheDocument();
    expect(svg).toHaveAttribute("viewBox", "392.75 10 446.25 123.5");
    expect(svg).toHaveAttribute("height", "124");
    expect(svg).toHaveAttribute("width", "447");

    const paths = container.querySelectorAll(".tactile-plate-paths > path");
    expect(paths).toHaveLength(2);
    // Основной контур начинается на базовой отметке y=73.5
    expect(paths[0]).toHaveAttribute("d", expect.stringContaining("M392.75 73.5H839V70"));
    // Проверяем неизменность верхнего радиуса (y=10)
    expect(paths[0]).toHaveAttribute("d", expect.stringContaining("779 10H456.25"));
  });

  it("пропорционально удлиняет вертикальные направляющие при extraHeight > 0", () => {
    const extra = 48;
    const { container } = render(<FigmaInputPlateFullBg extraHeight={extra} />);
    const svg = container.querySelector("svg");
    expect(svg).toBeInTheDocument();
    // Высота viewBox увеличивается ровно на 48: 123.5 + 48 = 171.5
    expect(svg).toHaveAttribute("viewBox", "392.75 10 446.25 171.5");
    expect(svg).toHaveAttribute("height", String(124 + extra));

    const paths = container.querySelectorAll(".tactile-plate-paths > path");
    // Нижняя кромка смещается вниз: 73.5 + 48 = 121.5
    expect(paths[0]).toHaveAttribute("d", expect.stringContaining("M392.75 121.5H839V70"));
    // Вертикальная вставка на стыке x=424.5: V(41.75 + 48) = V89.75
    expect(paths[0]).toHaveAttribute("d", expect.stringContaining("V89.75"));
    // Верхняя кромка и верхнее скругление радиусом 60px остаются абсолютно неизменными
    expect(paths[0]).toHaveAttribute("d", expect.stringContaining("C821.426 10 807.284 10 779 10H456.25"));
    // Хвост подложки под док также смещается на 48: 73 + 48 = 121
    expect(paths[1]).toHaveAttribute("d", expect.stringContaining("M779 121H839"));
  });

  it("корректно обрабатывает отрицательные значения extraHeight, приравнивая к 0", () => {
    const { container } = render(<FigmaInputPlateFullBg extraHeight={-20} />);
    const svg = container.querySelector("svg");
    expect(svg).toHaveAttribute("viewBox", "392.75 10 446.25 123.5");
    expect(svg).toHaveAttribute("height", "124");
  });

  it("не смешивает SVG материалы нескольких панелей при изменении высоты", () => {
    const plates = (height: number) => <>
      <FigmaInputPlateFullBg extraHeight={height} />
      <FigmaInputPlateFullBg />
      <FigmaDockBg />
      <FigmaSquareButtonBg />
    </>;
    const { container, rerender } = render(plates(0));
    const ids = () => [...container.querySelectorAll("[id]")].map((node) => node.id);
    const originalIds = ids();
    expect(new Set(originalIds).size).toBe(originalIds.length);
    rerender(plates(100));
    expect(ids()).toEqual(originalIds);
    for (const node of container.querySelectorAll("use")) {
      const target = container.querySelector(`[id="${node.getAttribute("href")?.slice(1)}"]`);
      expect(target).not.toBeNull();
      expect(target?.closest("svg")).toBe(node.closest("svg"));
    }
    for (const node of container.querySelectorAll('[fill^="url("]')) {
      const targetId = node.getAttribute("fill")!.slice(5, -1);
      const target = container.querySelector(`[id="${targetId}"]`);
      expect(target?.closest("svg")).toBe(node.closest("svg"));
    }
  });

  it.each([0, 48, 200])("продолжает правый контур до конца хвоста без обводки стыка при высоте %i", (height) => {
    const { container } = render(<FigmaInputPlateFullBg extraHeight={height} />);
    const focus = container.querySelector(".tactile-plate-focus path")!;
    const bevel = container.querySelector(".tactile-plate-edge path")!;
    const outline = focus.getAttribute("d")!;
    expect(outline).toBe(bevel.getAttribute("d"));
    expect(outline).toMatch(new RegExp(`^M839 ${133.5 + height}V70`));
    expect(outline).toContain("C821.426 10 807.284 10 779 10H456.25");
    expect(outline).toMatch(new RegExp(`392.75 ${73.5 + height}$`));
    expect(outline).not.toContain("Z");
    expect(outline).not.toContain("H839");
    expect(outline).not.toContain("L830.213");
    expect(container.querySelector(".tactile-plate-focus use")).toBeNull();
  });
});
