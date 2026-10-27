export const SETTINGS_SECTIONS = {
  conversation: { title: "Разговор", description: "Участие Iris в беседе, паузы и перебивания.", words: "поведение участники инициативность conversation" },
  voice: { title: "Голос Iris", description: "Звучание, скорость, подача и произношение слов.", words: "речь темп выразительность voice tts" },
  "voice-devices": { title: "Микрофон и звук", description: "Устройства ввода и вывода, шумоподавление и эхо.", words: "устройства гарнитура колонки наушники audio headphones microphone" },
  "voice-recognition": { title: "Распознавание речи", description: "Язык голосового ввода и исправление неправильно услышанных слов.", words: "распознавание словарь термины stt language" },
  avatar: { title: "Аватар", description: "Размещение и видимость аватара Iris.", words: "оверлей размер масштаб клики overlay avatar" },
  internet: { title: "Поиск в интернете", description: "Проверка актуальной информации во время разговора.", words: "веб поиск источники tavily search интернет" },
  environment: { title: "Город, погода и новости", description: "Местоположение и сводки для контекста беседы.", words: "город время местоположение погода новости weather location" },
  memory: { title: "Сохранение и приватность", description: "Долгосрочная память, история и режим инкогнито.", words: "память факты запоминать сохранять incognito privacy memory" },
  backups: { title: "Резервные копии", description: "Создание, экспорт и восстановление копий данных Iris.", words: "копия архив zip импорт экспорт backup restore" },
  maintenance: { title: "Управление данными", description: "Удаление истории и управление сохранённой памятью.", words: "очистить удалить архив история память сброс данные" },
  "system-interface": { title: "Интерфейс и окно", description: "Язык приложения, запуск и размер окна.", words: "язык анимация запуск фиксация восстановить размер окно window resize interface" },
  notifications: { title: "Уведомления", description: "Панель фонового разговора и сообщения о поиске.", words: "уведомление субтитры фон разговор поиск notifications" },
  shortcuts: { title: "Сочетания клавиш", description: "Клавиши для частых действий в Iris.", words: "горячие клавиши бинды привязка раскладка клавиатура shortcuts hotkeys keyboard" },
  "api-keys": { title: "API-ключи", description: "Подключение модели для общения и дополнительных сервисов.", words: "ключ api deepseek coding tavily brave serper подключение" },
  models: { title: "Локальные модели", description: "Загрузка моделей для голоса и памяти.", words: "модель скачать загрузка веса папка место gigaam teratts models" },
  "token-usage": { title: "Расходы и запросы", description: "Примерная стоимость, токены и журнал запросов Iris.", words: "расход стоимость токены статистика деньги usage cost" },
  "system-overview": { title: "Состояние Iris", description: "Готовность подключений и компонентов.", words: "готовность система подключение диагностика connection" },
  developer: { title: "Для разработчиков", description: "Режим разработчика, тонкая настройка и инструменты проверки.", words: "разработчик режим диагностика qa studio vad буфер тайминги индекс developer" },
  events: { title: "Журнал событий", description: "Технические события и диагностика.", words: "ошибка журнал события лог логирование events logs" },
  about: { title: "О приложении", description: "Версия Iris и история обновлений.", words: "версия обновление что нового changelog change log release notes updates" },
} as const;

export type SettingsPageId = keyof typeof SETTINGS_SECTIONS;
export type SettingsSection = SettingsPageId | "system-window" | "voice-advanced";
export type SettingsNavigationRequest = { section: SettingsSection; target?: "deepseek" | "coding" | "tavily"; focusId?: string; id: number };
export const normalizeSettingsSection = (section: SettingsSection): SettingsPageId =>
  section === "system-window" ? "system-interface" : section === "voice-advanced" ? "developer" : section;

export const SETTINGS_GROUPS: { id: string; label: string; icon: string; sections: SettingsPageId[] }[] = [
  { id: "conversation", label: "Общение", icon: "conversation", sections: ["conversation", "voice", "voice-devices", "voice-recognition", "avatar"] },
  { id: "internet", label: "Интернет и окружение", icon: "internet", sections: ["internet", "environment"] },
  { id: "data", label: "Память и данные", icon: "data", sections: ["memory", "backups", "maintenance"] },
  { id: "application", label: "Приложение", icon: "application", sections: ["system-interface", "notifications", "shortcuts"] },
  { id: "connections", label: "Подключения", icon: "connections", sections: ["api-keys", "models", "token-usage"] },
  { id: "diagnostics", label: "Диагностика", icon: "diagnostics", sections: ["system-overview", "developer", "events"] },
];

export type SettingsSearchEntry = { section: SettingsPageId | "changelog"; title: string; words: string; dev: boolean; focusId?: string };
export const SETTINGS_SEARCH: SettingsSearchEntry[] = [
  ...Object.entries(SETTINGS_SECTIONS).map(([section, meta]) => ({ section: section as SettingsPageId, title: meta.title, words: meta.words, dev: section === "events" })),
  { section: "voice", title: "Произношение слов", words: "словарь произношение имя как произносить tts pronunciation", dev: false, focusId: "voice-pronunciations" },
  { section: "conversation", title: "Паузы и перебивания", words: "пауза ждать перебить перебивание чувствительность", dev: false, focusId: "conversation-timing" },
  { section: "memory", title: "Режим инкогнито", words: "инкогнито не сохранять разговор приватность incognito", dev: false, focusId: "memory-incognito" },
  { section: "api-keys", title: "Ключ поиска Tavily", words: "api ключ поиска интернет tavily", dev: false, focusId: "credential-tavily" },
  { section: "api-keys", title: "Ключ Coding Agent", words: "api ключ coding код агент разработка", dev: false, focusId: "credential-coding" },
  { section: "system-interface", title: "Размер окна", words: "окно размер фиксация window resize", dev: false, focusId: "settings-system-window" },
  { section: "changelog", title: "Что нового", words: "история обновлений changelog release notes", dev: false },
];

export function searchSettings(query: string, developerMode: boolean) {
  const normalize = (value: string) => value.toLowerCase().replace(/ё/g, "е");
  const words = normalize(query).split(/\s+/).filter(Boolean);
  return SETTINGS_SEARCH.filter(item => (!item.dev || developerMode) && words.every(word => normalize(`${item.title} ${item.words}`).includes(word)));
}
