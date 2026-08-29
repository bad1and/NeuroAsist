export interface MoodVisuals {
  labelRu: string;
  colors: [string, string, string];
  speed: number;
}

export const MOOD_MAP: Record<string, MoodVisuals> = {
  "neutral": {
    labelRu: "Спокойное",
    colors: ["#6e33cc", "#ffc105", "#f585ff"], // More vibrant neutral, similar to screenshot 2
    speed: 2.5,
  },
  "joy": {
    labelRu: "Радость",
    colors: ["#ff5500", "#ffc800", "#ff8800"], 
    speed: 3,
  },
  "sadness": {
    labelRu: "Грусть",
    colors: ["#1e3b70", "#29539b", "#4f84c4"], 
    speed: 1,
  },
  "anger": {
    labelRu: "Злость",
    colors: ["#ff0000", "#990000", "#ff3333"], 
    speed: 4,
  },
  "fear": {
    labelRu: "Страх",
    colors: ["#3b0944", "#5f1854", "#982c75"], 
    speed: 3.5,
  },
  "surprise": {
    labelRu: "Удивление",
    colors: ["#00e5ff", "#0055ff", "#00ffff"], 
    speed: 3,
  },
  "curiosity": {
    labelRu: "Любопытство",
    colors: ["#1abc9c", "#f1c40f", "#3498db"], 
    speed: 2.5,
  },
  "affection": {
    labelRu: "Привязанность",
    colors: ["#ff6a88", "#ff9a9e", "#fecfef"], 
    speed: 2,
  },
  "amusement": {
    labelRu: "Веселье",
    colors: ["#ff5500", "#f585ff", "#00e5ff"], 
    speed: 3.5,
  },
  "boredom": {
    labelRu: "Скука",
    colors: ["#7f8c8d", "#bdc3c7", "#95a5a6"], 
    speed: 0.8,
  },
  "confusion": {
    labelRu: "Замешательство",
    colors: ["#d98880", "#c39bd3", "#7fb3d5"], 
    speed: 2.8,
  }
};

export const STRENGTH_MAP: Record<string, string> = {
  "muted": "Приглушенное",
  "low": "Слабо выражено",
  "medium": "Умеренно",
  "high": "Ярко выражено",
  "intense": "Очень сильно",
};

export function getMoodVisuals(emotion?: string): MoodVisuals {
  const key = (emotion || "neutral").toLowerCase();
  return MOOD_MAP[key] || MOOD_MAP["neutral"];
}

export function getStrengthLabel(strength?: string): string {
  const key = (strength || "medium").toLowerCase();
  return STRENGTH_MAP[key] || "Умеренно";
}
