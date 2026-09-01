// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FigmaInputPlateFullBg } from "../FigmaIcons";

describe("FigmaInputPlateFullBg", () => {
  it("рендерит базовую SVG подложку с extraHeight = 0 без искажений", () => {
    const { container } = render(<FigmaInputPlateFullBg data-testid="plate" />);
    const svg = container.querySelector("svg");
    expect(svg).toBeInTheDocument();
    expect(svg).toHaveAttribute("viewBox", "392.75 10 446.25 123.5");
    expect(svg).toHaveAttribute("height", "124");
    expect(svg).toHaveAttribute("width", "447");

    const paths = container.querySelectorAll("path");
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

    const paths = container.querySelectorAll("path");
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
});
