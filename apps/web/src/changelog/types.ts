export interface ReleaseImage {
  /** Bundled public asset, e.g. /changelog/1.1.0/search.webp. No remote requests. */
  src: string;
  alt: string;
  width: number;
  height: number;
  caption?: string;
}

export interface ReleaseSection {
  title: string;
  kind: "new" | "improved" | "fixed";
  items: { title: string; description: string; image?: ReleaseImage }[];
}

export interface ReleaseNote {
  version: string;
  status: "released" | "preview";
  /** Actual release date, YYYY-MM-DD. Omit for an unpublished build. */
  date?: string;
  title: string;
  /** One short sentence for the persistent notification (up to 90 characters). */
  summary: string;
  intro: string;
  highlight?: { label: string; title: string; description: string; image?: ReleaseImage };
  sections: ReleaseSection[];
  note?: string;
}
