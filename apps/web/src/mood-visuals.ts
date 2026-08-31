export interface MoodVisuals {
  labelRu: string;
  colors: [string, string, string]; // [coreColor, fringeColor, accentColor]
  speed: number;
  warp: number;
  radius?: number;
}

export const MOOD_MAP: Record<string, MoodVisuals> = {
  "neutral": {
    labelRu: "Спокойное",
    colors: ["#c4b5fd", "#818cf8", "#38bdf8"], // Soft Lavender Iris, Indigo Amethyst, Cosmic Cyan
    speed: 1.0,
    warp: 0.14,
  },
  "joy": {
    labelRu: "Радость",
    colors: ["#fde047", "#fb7185", "#c084fc"], // Warm Solar Amber, Coral Rose, Radiant Orchid-Lilac
    speed: 2.1,
    warp: 0.26,
  },
  "happy": {
    labelRu: "Счастье",
    colors: ["#fde047", "#fb7185", "#c084fc"],
    speed: 2.1,
    warp: 0.26,
  },
  "sadness": {
    labelRu: "Грусть",
    colors: ["#93c5fd", "#4338ca", "#6b21a8"], // Ice Blue Sheen, Deep Twilight Indigo, Midnight Violet
    speed: 0.6,
    warp: 0.08,
  },
  "sad": {
    labelRu: "Грусть",
    colors: ["#93c5fd", "#4338ca", "#6b21a8"],
    speed: 0.6,
    warp: 0.08,
  },
  "anger": {
    labelRu: "Злость",
    colors: ["#f87171", "#dc2626", "#581c87"], // Ember Rose, Ruby Crimson, Deep Garnet Violet
    speed: 2.6,
    warp: 0.38,
  },
  "angry": {
    labelRu: "Злость",
    colors: ["#f87171", "#dc2626", "#581c87"],
    speed: 2.6,
    warp: 0.38,
  },
  "annoyed": {
    labelRu: "Раздражение",
    colors: ["#fb923c", "#e11d48", "#701a75"], // Spicy Amber, Vivid Crimson-Rose, Smoldering Plum
    speed: 2.3,
    warp: 0.32,
  },
  "irritation": {
    labelRu: "Раздражение",
    colors: ["#fb923c", "#e11d48", "#701a75"],
    speed: 2.3,
    warp: 0.32,
  },
  "fear": {
    labelRu: "Страх",
    colors: ["#fcd34d", "#9333ea", "#3b0764"], // Strobe Amber, Electric Purple, Abyssal Amethyst
    speed: 1.6,
    warp: 0.24,
  },
  "anxiety": {
    labelRu: "Тревога",
    colors: ["#fcd34d", "#9333ea", "#3b0764"],
    speed: 1.6,
    warp: 0.24,
  },
  "concerned": {
    labelRu: "Опасение",
    colors: ["#fed7aa", "#a855f7", "#4c1d95"], // Soft Peach Mist, Misty Mauve, Dusk Violet
    speed: 1.3,
    warp: 0.18,
  },
  "embarrassed": {
    labelRu: "Смущение",
    colors: ["#fbcfe8", "#f43f5e", "#a855f7"], // Blush Silk, Velvet Rose, Lilac Veil
    speed: 1.2,
    warp: 0.16,
  },
  "embarrassment": {
    labelRu: "Смущение",
    colors: ["#fbcfe8", "#f43f5e", "#a855f7"],
    speed: 1.2,
    warp: 0.16,
  },
  "surprise": {
    labelRu: "Удивление",
    colors: ["#f0abfc", "#06b6d4", "#7c3aed"], // Neon Orchid, Electric Cyan Aurora, Royal Violet
    speed: 2.0,
    warp: 0.30,
  },
  "surprised": {
    labelRu: "Удивление",
    colors: ["#f0abfc", "#06b6d4", "#7c3aed"],
    speed: 2.0,
    warp: 0.30,
  },
  "thinking": {
    labelRu: "Размышление",
    colors: ["#38bdf8", "#6366f1", "#9333ea"], // Neural Cyan, Electric Indigo, Biolum Violet
    speed: 1.8,
    warp: 0.20,
  },
  "interest": {
    labelRu: "Интерес",
    colors: ["#34d399", "#0284c7", "#a855f7"],
    speed: 1.8,
    warp: 0.22,
  },
  "curiosity": {
    labelRu: "Любопытство",
    colors: ["#34d399", "#0284c7", "#a855f7"], // Ethereal Mint, Sapphire Blue, Luminous Purple
    speed: 1.9,
    warp: 0.24,
  },
  "affection": {
    labelRu: "Привязанность",
    colors: ["#fda4af", "#e11d48", "#c084fc"], // Cherry Blossom, Crimson Romance, Pastel Iris
    speed: 1.2,
    warp: 0.16,
  },
  "love": {
    labelRu: "Нежность",
    colors: ["#fda4af", "#e11d48", "#c084fc"],
    speed: 1.2,
    warp: 0.16,
  },
  "smirk": {
    labelRu: "Ухмылка",
    colors: ["#f472b6", "#8b5cf6", "#06b6d4"], // Playful Fuchsia, Electric Violet, Neon Aqua Spark
    speed: 1.5,
    warp: 0.22,
  },
  "playfulness": {
    labelRu: "Игривость",
    colors: ["#f472b6", "#8b5cf6", "#06b6d4"],
    speed: 1.5,
    warp: 0.22,
  },
  "amusement": {
    labelRu: "Веселье",
    colors: ["#fde047", "#f43f5e", "#a855f7"], // Golden Spark, Vibrant Coral, Party Orchid
    speed: 2.3,
    warp: 0.28,
  },
  "boredom": {
    labelRu: "Скука",
    colors: ["#cbd5e1", "#64748b", "#6d28d9"], // Misty Slate, Steel Dusk, Faint Violet Shadow
    speed: 0.7,
    warp: 0.10,
  },
  "confusion": {
    labelRu: "Замешательство",
    colors: ["#e2e8f0", "#818cf8", "#0ea5e9"], // Prismatic Mist, Lavender Indigo, Sky Azure
    speed: 1.6,
    warp: 0.28,
  },
  "hurt": {
    labelRu: "Обида",
    colors: ["#fda4af", "#9f1239", "#4a044e"], // Fragile Rose Crystal, Deep Bruised Wine, Shadow Plum
    speed: 0.8,
    warp: 0.12,
  },
  "fatigue": {
    labelRu: "Усталость",
    colors: ["#94a3b8", "#475569", "#3b2d54"], // Lavender Ash, Dusk Slate, Muted Iris Night
    speed: 0.5,
    warp: 0.07,
  },
  "focused": {
    labelRu: "Концентрация",
    colors: ["#38bdf8", "#4f46e5", "#7c3aed"], // Laser Sapphire, Cobalt Flux, Deep Violet Field
    speed: 1.4,
    warp: 0.14,
  },
  "grateful": {
    labelRu: "Благодарность",
    colors: ["#fde68a", "#db2777", "#7c3aed"], // Honey Gold, Velvet Magenta, Warm Amethyst
    speed: 1.1,
    warp: 0.16,
  },
  "sleepy": {
    labelRu: "Сонливость",
    colors: ["#818cf8", "#1e1b4b", "#312e81"], // Nocturnal Lavender, Midnight Deep, Cosmic Haze
    speed: 0.4,
    warp: 0.06,
  },
};

export const STRENGTH_MAP: Record<string, string> = {
  "muted": "Приглушенное",
  "subtle": "Сдержанное",
  "low": "Слабо выражено",
  "medium": "Умеренно",
  "high": "Ярко выражено",
  "intense": "Очень сильно",
};

export function getMoodVisuals(emotion?: string): MoodVisuals {
  const key = (emotion || "neutral").toLowerCase().trim();
  // Direct match
  if (MOOD_MAP[key]) return MOOD_MAP[key];

  // Russian alias support
  if (key === "радость" || key === "счастье" || key === "радостное") return MOOD_MAP["joy"];
  if (key === "грусть" || key === "печаль" || key === "грустное" || key === "тоска") return MOOD_MAP["sadness"];
  if (key === "злость" || key === "гнев" || key === "злое" || key === "ярость") return MOOD_MAP["anger"];
  if (key === "раздражение" || key === "досада" || key === "раздраженное") return MOOD_MAP["annoyed"];
  if (key === "страх" || key === "тревога" || key === "тревожность" || key === "испуг") return MOOD_MAP["fear"];
  if (key === "опасение" || key === "беспокойство" || key === "настороженность") return MOOD_MAP["concerned"];
  if (key === "смущение" || key === "неловкость" || key === "стыд") return MOOD_MAP["embarrassed"];
  if (key === "удивление" || key === "шок" || key === "изумление") return MOOD_MAP["surprise"];
  if (key === "размышление" || key === "думает" || key === "задумчивость" || key === "мысли") return MOOD_MAP["thinking"];
  if (key === "интерес") return MOOD_MAP["interest"];
  if (key === "любопытство" || key === "любознательность") return MOOD_MAP["curiosity"];
  if (key === "привязанность" || key === "нежность" || key === "любовь" || key === "теплота") return MOOD_MAP["affection"];
  if (key === "ухмылка" || key === "игривость" || key === "лукавство") return MOOD_MAP["smirk"];
  if (key === "веселье" || key === "смех" || key === "забава") return MOOD_MAP["amusement"];
  if (key === "скука" || key === "апатия" || key === "уныние") return MOOD_MAP["boredom"];
  if (key === "замешательство" || key === "растерянность" || key === "непонимание") return MOOD_MAP["confusion"];
  if (key === "обида" || key === "уязвимость" || key === "уязвленность") return MOOD_MAP["hurt"];
  if (key === "усталость" || key === "истощение" || key === "утомление") return MOOD_MAP["fatigue"];
  if (key === "концентрация" || key === "фокус" || key === "поток" || key === "сосредоточенность") return MOOD_MAP["focused"];
  if (key === "благодарность" || key === "признательность") return MOOD_MAP["grateful"];
  if (key === "сонливость" || key === "дремота" || key === "сон") return MOOD_MAP["sleepy"];
  if (key === "спокойное" || key === "спокойствие" || key === "нейтральное" || key === "гармония") return MOOD_MAP["neutral"];

  return MOOD_MAP["neutral"];
}

export function getStrengthLabel(strength?: string): string {
  const key = (strength || "medium").toLowerCase();
  return STRENGTH_MAP[key] || "Умеренно";
}

