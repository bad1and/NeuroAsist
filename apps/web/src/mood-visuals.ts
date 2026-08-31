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
    colors: ["#c084fc", "#6366f1", "#38bdf8"], // Luminous Lilac, Electric Indigo, Sky Cyan
    speed: 1.0,
    warp: 0.15,
  },
  "joy": {
    labelRu: "Радость",
    colors: ["#fde047", "#f97316", "#ec4899"], // Warm Gold, Vivid Tangerine, Hot Pink
    speed: 2.2,
    warp: 0.28,
  },
  "happy": {
    labelRu: "Счастье",
    colors: ["#fde047", "#f97316", "#ec4899"],
    speed: 2.2,
    warp: 0.28,
  },
  "sadness": {
    labelRu: "Грусть",
    colors: ["#7dd3fc", "#1e3a8a", "#4338ca"], // Ice Blue, Deep Navy, Twilight Indigo
    speed: 0.6,
    warp: 0.08,
  },
  "sad": {
    labelRu: "Грусть",
    colors: ["#7dd3fc", "#1e3a8a", "#4338ca"],
    speed: 0.6,
    warp: 0.08,
  },
  "anger": {
    labelRu: "Злость",
    colors: ["#fca5a5", "#dc2626", "#7f1d1d"], // Hot Ember, Intense Crimson, Dark Garnet
    speed: 2.8,
    warp: 0.40,
  },
  "angry": {
    labelRu: "Злость",
    colors: ["#fca5a5", "#dc2626", "#7f1d1d"],
    speed: 2.8,
    warp: 0.40,
  },
  "annoyed": {
    labelRu: "Раздражение",
    colors: ["#fdba74", "#ea580c", "#991b1b"],
    speed: 2.4,
    warp: 0.35,
  },
  "fear": {
    labelRu: "Страх",
    colors: ["#fba94b", "#86198f", "#4c1d95"], // Warm Amber, Deep Plum, Dark Violet
    speed: 1.6,
    warp: 0.25,
  },
  "concerned": {
    labelRu: "Опасение",
    colors: ["#fed7aa", "#a21caf", "#581c87"],
    speed: 1.4,
    warp: 0.20,
  },
  "embarrassed": {
    labelRu: "Смущение",
    colors: ["#fecdd3", "#fb7185", "#be185d"], // Soft Rose, Coral Pink, Deep Rose
    speed: 1.3,
    warp: 0.16,
  },
  "surprise": {
    labelRu: "Удивление",
    colors: ["#f0abfc", "#06b6d4", "#8b5cf6"], // Neon Orchid, Electric Aqua, Vivid Purple
    speed: 2.0,
    warp: 0.32,
  },
  "surprised": {
    labelRu: "Удивление",
    colors: ["#f0abfc", "#06b6d4", "#8b5cf6"],
    speed: 2.0,
    warp: 0.32,
  },
  "thinking": {
    labelRu: "Размышление",
    colors: ["#22d3ee", "#10b981", "#818cf8"], // Biolum Cyan, Cyber Emerald, Neural Indigo
    speed: 1.8,
    warp: 0.22,
  },
  "curiosity": {
    labelRu: "Любопытство",
    colors: ["#34d399", "#0284c7", "#a855f7"], 
    speed: 1.9,
    warp: 0.26,
  },
  "affection": {
    labelRu: "Привязанность",
    colors: ["#fda4af", "#f43f5e", "#c084fc"], // Soft Cherry, Warm Rose, Pastel Violet
    speed: 1.2,
    warp: 0.18,
  },
  "smirk": {
    labelRu: "Ухмылка",
    colors: ["#f472b6", "#a855f7", "#38bdf8"], 
    speed: 1.5,
    warp: 0.22,
  },
  "amusement": {
    labelRu: "Веселье",
    colors: ["#fbbf24", "#f43f5e", "#06b6d4"], 
    speed: 2.4,
    warp: 0.30,
  },
  "boredom": {
    labelRu: "Скука",
    colors: ["#cbd5e1", "#64748b", "#94a3b8"], // Muted Mist, Slate, Light Slate
    speed: 0.7,
    warp: 0.10,
  },
  "confusion": {
    labelRu: "Замешательство",
    colors: ["#e2e8f0", "#a855f7", "#0ea5e9"], 
    speed: 1.7,
    warp: 0.32,
  },
};

export const STRENGTH_MAP: Record<string, string> = {
  "muted": "Приглушенное",
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
  if (key === "радость" || key === "счастье") return MOOD_MAP["joy"];
  if (key === "грусть" || key === "печаль") return MOOD_MAP["sadness"];
  if (key === "злость" || key === "гнев") return MOOD_MAP["anger"];
  if (key === "страх" || key === "тревога") return MOOD_MAP["fear"];
  if (key === "удивление") return MOOD_MAP["surprise"];
  if (key === "размышление" || key === "думает") return MOOD_MAP["thinking"];
  if (key === "любопытство") return MOOD_MAP["curiosity"];
  if (key === "привязанность" || key === "нежность") return MOOD_MAP["affection"];
  if (key === "веселье") return MOOD_MAP["amusement"];
  if (key === "скука") return MOOD_MAP["boredom"];
  if (key === "замешательство") return MOOD_MAP["confusion"];

  return MOOD_MAP["neutral"];
}

export function getStrengthLabel(strength?: string): string {
  const key = (strength || "medium").toLowerCase();
  return STRENGTH_MAP[key] || "Умеренно";
}
