import type { ReleaseNote } from "./types";

declare const __IRIS_APP_VERSION__: string;
export const APP_VERSION = __IRIS_APP_VERSION__;

/** SemVer order, including numeric prerelease identifiers (rc.10 > rc.2). */
export function compareVersions(left: string, right: string): number {
  const split = (value: string) => {
    const [core, prerelease] = value.split("+")[0].split(/-(.*)/s);
    return { core: core.split(".").map(Number), pre: prerelease?.split(".") };
  };
  const a = split(left), b = split(right);
  for (let index = 0; index < 3; index++) {
    if (a.core[index] !== b.core[index]) return a.core[index] - b.core[index];
  }
  if (!a.pre || !b.pre) return a.pre ? -1 : b.pre ? 1 : 0;
  for (let index = 0; index < Math.max(a.pre.length, b.pre.length); index++) {
    const x = a.pre[index], y = b.pre[index];
    if (x === y) continue;
    if (x === undefined || y === undefined) return x === undefined ? -1 : 1;
    const xn = /^\d+$/.test(x), yn = /^\d+$/.test(y);
    if (xn && yn) return Number(x) - Number(y);
    if (xn !== yn) return xn ? -1 : 1;
    return x < y ? -1 : 1;
  }
  return 0;
}

const entries = import.meta.glob<ReleaseNote>("./releases/*.ts", { eager: true, import: "default" });
export const releaseNotes = Object.values(entries)
  .filter(release => release.version === APP_VERSION || (release.status === "released" && compareVersions(release.version, APP_VERSION) < 0))
  .sort((a, b) => compareVersions(b.version, a.version));

// Keep the installed version truthful even if a future build omits its entry.
export const currentRelease: ReleaseNote = releaseNotes.find(release => release.version === APP_VERSION) ?? {
  version: APP_VERSION, status: "preview", title: "Новая сборка Iris",
  summary: "Установлена новая версия Iris. Подробности обновления появятся здесь.",
  intro: "Для этой сборки пока нет подробного описания изменений.", sections: [],
};

export const availableReleases = releaseNotes.some(release => release.version === APP_VERSION)
  ? releaseNotes : [currentRelease, ...releaseNotes];

export function releaseDate(date?: string): string {
  return date ? new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" }).format(new Date(`${date}T00:00:00Z`)) : "В разработке";
}
