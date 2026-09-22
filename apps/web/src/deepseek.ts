export type DeepSeekModel = "deepseek-flash" | "deepseek-v4-pro";

type DeepSeekTokenRates = {
  cacheHit: number;
  cacheMiss: number;
  output: number;
};

export type DeepSeekUsageForPricing = {
  prompt_tokens?: number;
  completion_tokens?: number;
  prompt_cache_hit_tokens?: number;
  prompt_cache_miss_tokens?: number;
  model?: string;
  timestamp?: number;
};

const FLASH_MODEL: DeepSeekModel = "deepseek-flash";
const PRO_MODEL: DeepSeekModel = "deepseek-v4-pro";

const MODEL_ALIASES: Record<string, DeepSeekModel> = {
  "deepseek-v4.1-flash": FLASH_MODEL,
  "deepseek-v4-flash": FLASH_MODEL,
  "deepseek-v4-flash-vision-exp": FLASH_MODEL,
  "deepseek-chat": FLASH_MODEL,
  "deepseek-reasoner": FLASH_MODEL,
  "deepseek-v4.1-pro": PRO_MODEL,
};

// USD per one million tokens, published by DeepSeek for V4.1 Flash/V4 Pro.
const FLASH_PEAK: DeepSeekTokenRates = { cacheHit: 0.006, cacheMiss: 0.30, output: 1.20 };
const FLASH_OFF_PEAK: DeepSeekTokenRates = { cacheHit: 0.003, cacheMiss: 0.15, output: 0.60 };
const PRO_PEAK: DeepSeekTokenRates = { cacheHit: 0.044, cacheMiss: 1.32, output: 3.96 };
const PRO_OFF_PEAK: DeepSeekTokenRates = { cacheHit: 0.022, cacheMiss: 0.66, output: 1.98 };

export function canonicalDeepSeekModel(model?: string): DeepSeekModel {
  const value = model?.trim().toLowerCase();
  if (!value || value === FLASH_MODEL) return FLASH_MODEL;
  if (value === PRO_MODEL) return PRO_MODEL;
  return MODEL_ALIASES[value] ?? FLASH_MODEL;
}

export function isDeepSeekPeakTime(timestamp = Date.now() / 1000): boolean {
  const seconds = timestamp > 1_000_000_000_000 ? timestamp / 1000 : timestamp;
  const moment = new Date(seconds * 1000);
  const day = moment.getUTCDay();
  if (day === 0 || day === 6) return false;
  const hour = moment.getUTCHours();
  return (hour >= 1 && hour < 4) || (hour >= 6 && hour < 10);
}

export function calculateDeepSeekCostUsd(tokens: DeepSeekUsageForPricing): number {
  const hit = Math.max(0, tokens.prompt_cache_hit_tokens ?? 0);
  const miss = Math.max(
    0,
    tokens.prompt_cache_miss_tokens
      ?? Math.max(0, (tokens.prompt_tokens ?? 0) - hit),
  );
  const completion = Math.max(0, tokens.completion_tokens ?? 0);
  const peak = isDeepSeekPeakTime(tokens.timestamp);
  const pro = canonicalDeepSeekModel(tokens.model) === PRO_MODEL;
  const rates = pro
    ? (peak ? PRO_PEAK : PRO_OFF_PEAK)
    : (peak ? FLASH_PEAK : FLASH_OFF_PEAK);
  return (
    (hit * rates.cacheHit)
    + (miss * rates.cacheMiss)
    + (completion * rates.output)
  ) / 1_000_000;
}
