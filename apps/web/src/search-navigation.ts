export type SearchFocus = { requestId: string; id: string; query: string; section?: "all" | "commitments" };
export type SearchDestination =
  | { kind: "history"; focus: SearchFocus }
  | { kind: "memory"; focus: SearchFocus }
  | { kind: "setting"; section: string };

export const SETTINGS_SEARCH = [
  { section: "conversation", title: "Живой разговор", words: "поведение участие инициативность паузы перебивание conversation", dev: false },
  { section: "environment", title: "Город и интернет", words: "поиск интернет погода новости город время местоположение search weather", dev: false },
  { section: "avatar", title: "Аватар", words: "аватар оверлей масштаб клики положение avatar overlay", dev: false },
  { section: "voice", title: "Голос", words: "голос скорость речь темп звучание выразительность voice speed", dev: false },
  { section: "voice-devices", title: "Устройства", words: "микрофон наушники звук запись устройство microphone audio headphones", dev: false },
  { section: "voice-recognition", title: "Распознавание", words: "словарь произношение распознавание термины stt tts", dev: false },
  { section: "voice-advanced", title: "Дополнительные параметры голоса", words: "буфер тайминги тестовые записи buffer", dev: true },
  { section: "memory", title: "Настройки памяти", words: "память инкогнито приватность memory incognito", dev: false },
  { section: "system-interface", title: "Интерфейс", words: "язык интерфейс разработчик developer language", dev: false },
  { section: "system-window", title: "Окно приложения", words: "размер окно фиксация восстановить window resize", dev: false },
  { section: "shortcuts", title: "Сочетания клавиш", words: "горячие клавиши бинды привязка раскладка клавиатура shortcuts hotkeys keyboard", dev: false },
  { section: "api-keys", title: "API-ключи", words: "ключ api deepseek tavily brave serper подключение", dev: false },
  { section: "token-usage", title: "Токены и расходы", words: "расходы стоимость токены статистика деньги usage cost", dev: false },
  { section: "system-overview", title: "Готовность системы", words: "готовность система подключение диагностика connection", dev: false },
  { section: "models", title: "Модели", words: "модель скачать загрузка веса место gigaam teratts models", dev: false },
  { section: "backups", title: "Резервные копии", words: "копия архив zip импорт экспорт восстановление backup restore", dev: false },
  { section: "maintenance", title: "Обслуживание данных", words: "очистка удалить индексы обслуживание", dev: true },
  { section: "events", title: "Журнал событий", words: "ошибка журнал события лог логирование events logs", dev: true },
];

export function searchSettings(query: string, developerMode: boolean) {
  const words = query.toLowerCase().replace(/ё/g, "е").split(/\s+/).filter(Boolean);
  return SETTINGS_SEARCH.filter(item => (!item.dev || developerMode) && words.every(word => `${item.title} ${item.words}`.toLowerCase().replace(/ё/g, "е").includes(word)));
}
