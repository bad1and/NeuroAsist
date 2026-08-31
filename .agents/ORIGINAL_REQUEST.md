# Original User Request

## Initial Request — 2026-08-30T03:30:17+03:00

Переработка раздела История (Journal) в React-приложении (d:\NeroPizda\NeuroAsist\apps\web):
1. R1. Двухпанельный интерфейс:
   - В src/journal.tsx слева список чатов (эпизодов), загружаемых через getTimelineJournal().
   - Справа область для просмотра сообщений выбранного чата через getTimelineMessages(50, episode.id) из api.ts.
   - Отображение сообщений как в основном чате (стили класса .message, разделение user / assistant).
2. R2. Выделение текущего чата:
   - Если у эпизода ended_at отсутствует (null), он визуально выделяется в списке слева (бэйдж / пульсирующая точка).
3. R3. Мобильная адаптивность и стили:
   - На узких экранах переключение на одну панель: показ списка -> при клике переход к сообщениям -> кнопка "Назад" для возврата к списку.
   - Добавить необходимые CSS классы (.journal-layout, .journal-sidebar, .journal-content) в src/styles.css.
4. Acceptance Criteria:
   - npm run build в apps/web завершается без ошибок.
   - npm run test в apps/web завершается без ошибок (существующие или обновленные тесты в ui.test.tsx).