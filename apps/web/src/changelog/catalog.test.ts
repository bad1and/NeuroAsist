import { describe, expect, it } from "vitest";
import { APP_VERSION, compareVersions, currentRelease, releaseNotes, releaseDate } from "./catalog";
import type { ReleaseNote } from "./types";

const entries = Object.entries(import.meta.glob<ReleaseNote>("./releases/*.ts", { eager: true, import: "default" }));
const images = import.meta.glob("/public/changelog/**/*.{webp,png,jpg,jpeg,svg,gif}", { eager: true, query: "?url", import: "default" });

describe("каталог обновлений", () => {
  it("содержит запись установленной версии и уникальные версии в правильных файлах", () => {
    expect(currentRelease.version).toBe(APP_VERSION);
    expect(releaseNotes.some(item => item.version === APP_VERSION)).toBe(true);
    expect(new Set(entries.map(([, item]) => item.version)).size).toBe(entries.length);
    for (const [path, release] of entries) {
      expect(path).toBe(`./releases/${release.version}.ts`);
      expect(release.version).toMatch(/^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$/);
      expect(release.title.trim()).not.toBe("");
      expect(release.intro.trim()).not.toBe("");
      expect(release.summary.trim().length).toBeGreaterThan(0);
      expect(release.summary.length).toBeLessThanOrEqual(90);
      if (release.status === "released") {
        expect(release.date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
        expect(new Date(`${release.date}T00:00:00Z`).toISOString().slice(0, 10)).toBe(release.date);
      } else expect(release.date).toBeUndefined();
      for (const image of [release.highlight?.image, ...release.sections.flatMap(section => section.items.map(item => item.image))].filter(item => item !== undefined)) {
        expect(image.src).toMatch(/^\/changelog\/[0-9A-Za-z.+-]+\/[\w.-]+\.(webp|png|jpe?g|svg|gif)$/i);
        expect(image.src.startsWith(`/changelog/${release.version}/`)).toBe(true);
        expect(images).toHaveProperty(`/public${image.src}`);
        expect(image.alt.trim()).not.toBe("");
        expect(image.width).toBeGreaterThan(0);
        expect(image.height).toBeGreaterThan(0);
      }
    }
  });

  it.each([
    ["1.10.0", "1.9.0"], ["1.0.0", "1.0.0-rc.10"], ["1.0.0-rc.10", "1.0.0-rc.2"],
    ["1.0.0-beta", "1.0.0-alpha"], ["1.0.0-rc.1", "1.0.0-rc"], ["1.0.0-beta.a", "1.0.0-beta.10"],
  ])("сортирует %s после %s", (newer, older) => {
    expect(compareVersions(newer, older)).toBeGreaterThan(0);
    expect(compareVersions(older, newer)).toBeLessThan(0);
    expect(compareVersions(newer, newer)).toBe(0);
  });

  it("не меняет порядок из-за метаданных сборки и форматирует даты без сдвига дня", () => {
    expect(compareVersions("1.0.0+build.1", "1.0.0+build.2")).toBe(0);
    expect(releaseDate("2026-10-26")).toBe("26 октября 2026 г.");
    expect(releaseDate()).toBe("В разработке");
  });
});
