import irisPortrait from "../../../assets/iris-overview-portrait.png";

// Preserve the supplied artwork, including its original transparency.
export const OVERVIEW_HERO_ART: { src: string; kind: "flora" | "portrait" } = { src: irisPortrait, kind: "portrait" };

export type OverviewArtwork = {
  id: string;
  src: string;
  title: string;
  description: string;
  author?: string;
  position?: string;
};

// Curated works are bundled with Iris. Author credit is shown when supplied.
export const OVERVIEW_ARTWORKS: readonly OverviewArtwork[] = [
  { id: "iris-pastel-portrait", src: "/brand/overview/iris-pastel-portrait.png", title: "Пастельный портрет", description: "Мягкий портрет Iris в лиловых и розовых тонах с белыми звёздами.", position: "center 38%" },
  { id: "iris-summer-sky", src: "/brand/overview/iris-summer-sky.png", title: "Под открытым небом", description: "Улыбающаяся Iris под синим небом с белыми облаками.", position: "center 90%" },
  { id: "iris-graphic-portrait", src: "/brand/overview/iris-graphic-portrait.png", title: "Лиловый взгляд", description: "Крупный план Iris с графичными линиями и цветочными деталями в сиреневых тонах." },
  { id: "iris-motion-poster", src: "/brand/overview/iris-motion-poster.png", title: "В движении", description: "Динамичный постер Iris с геометрическими формами на кремовом фоне." },
  { id: "iris-assistant-project", src: "/brand/overview/iris-assistant-project.png", title: "Assistant Project: Iris", description: "Фиолетовый типографический постер с Iris внутри крупных букв её имени." },
  { id: "iris-always-with-you", src: "/brand/overview/iris-always-with-you.png", title: "Всегда рядом", description: "Iris на светло-голубом фоне с фиолетовым кругом и декоративной графикой.", position: "center 40%" },
];
