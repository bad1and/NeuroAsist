export type EventLevel = "debug" | "info" | "warning" | "error" | "critical";

export type BackendEvent = {
  id: string;
  type: string;
  level: EventLevel;
  message: string;
  created_at: string;
  metadata: Record<string, unknown>;
};

export type ChatResponse = {
  reply: string;
  emotion: string;
  intent: string;
};

export type StatusResponse = {
  app_name: string;
  version: string;
  backend: string;
  llm_provider: string;
  llm_model: string;
  api_key_configured: boolean;
  database: string;
};

export type PublicSettings = {
  provider: string;
  model: string;
  personality: string;
  chat_history_limit: number;
  log_level: string;
  api_key_configured: boolean;
  available_models: string[];
  available_personalities: string[];
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  emotion?: string;
  intent?: string;
};
