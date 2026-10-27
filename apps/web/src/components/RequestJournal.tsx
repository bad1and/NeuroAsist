import { useId, useLayoutEffect, useRef } from "react";
import { animate, prefersReducedMotion, stagger } from "../animations/core";
import {
  IconInterfaceChevronLeft as ChevronLeft, IconInterfaceChevronRight as ChevronRight,
  IconInterfaceRefresh as Refresh, IconInterfaceCheck as Check,
  IconInterfaceAlertTriangle as AlertTriangle, IconInterfaceActivity as Activity,
  IconInterfaceCopy as Copy,
} from "../CustomIcons";
import { CustomSelect } from "./CustomSelect";
import { SlidingSegments } from "./SlidingSegments";
import { MaterialButton } from "./MaterialButton";
import { Disclosure } from "./Disclosure";
import { formatTokens } from "./expenses";
import type { TokenRecordItem, TokenRecordsResponse } from "../types";
import "./RequestJournal.css";

const SHORT_CATEGORIES: Record<string, string> = { all: "Все", chat: "Диалог", memory: "Память", guards: "Проверки", coding: "Код" };
const timeFormat = new Intl.DateTimeFormat("ru-RU", { hour: "2-digit", minute: "2-digit" });
const dayFormat = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short" });
const fullDateFormat = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit", second: "2-digit" });
function latency(value: number) {
  return value >= 1000 ? `${(value / 1000).toLocaleString("ru-RU", { maximumFractionDigits: 2 })} с`
    : `${value.toLocaleString("ru-RU", { maximumFractionDigits: 0 })} мс`;
}
const counted = (record: TokenRecordItem, value: number) => record.usage_available ? formatTokens(value) : "—";

interface RequestJournalProps<Category extends string> {
  records: TokenRecordsResponse | null;
  loading: boolean;
  error: string | null;
  visible: boolean;
  categories: { id: Category; label: string }[];
  category: Category;
  onCategory: (value: Category) => void;
  purpose: string;
  purposeOptions: [string, string][];
  purposeLabels: Record<string, string>;
  onPurpose: (value: string) => void;
  onClearFilters: () => void;
  onRefresh: () => void;
  onInspect: (record: TokenRecordItem) => void;
  page: number;
  pageSize: number;
  onPage: (page: number) => void;
}

export function RequestJournal<Category extends string>({ records, loading, error, visible, categories, category, onCategory,
  purpose, purposeOptions, purposeLabels, onPurpose, onClearFilters, onRefresh, onInspect, page, pageSize, onPage }: RequestJournalProps<Category>) {
  const root = useRef<HTMLElement>(null);
  const id = useId();
  const items = records?.items ?? [];
  const totalPages = Math.max(1, Math.ceil((records?.total ?? 0) / pageSize));
  const filtered = category !== "all" || Boolean(purpose);
  useLayoutEffect(() => {
    if (!visible || !root.current || prefersReducedMotion()) return;
    if (loading) {
      const skeleton = root.current.querySelector(".request-log-skeleton");
      if (!skeleton) return;
      const motion = animate(skeleton, { opacity: [.35, .7, .35], duration: 1400, ease: "inOutSine", loop: true });
      return () => { motion.revert(); };
    }
    const rows = Array.from(root.current.querySelectorAll(".request-log-item")).slice(0, 8);
    if (!rows.length) return;
    const motion = animate(rows, { opacity: [.35, 1], translateY: [4, 0], duration: 220, delay: stagger(16), ease: "outCubic" });
    return () => { motion.revert(); };
  }, [records, loading, visible]);

  return <section ref={root} className="request-journal" aria-labelledby={`${id}-title`}>
    <div className="request-log-heading">
      <div><h3 id={`${id}-title`}>История запросов</h3><p>За всё время{records && !loading && !error ? ` · ${formatTokens(records.total)} записей` : ""}</p></div>
      <MaterialButton appearance="quiet" materialKey="requests.refresh" className="request-log-refresh"
        onClick={onRefresh} disabled={loading} aria-label="Обновить журнал запросов" title="Обновить журнал запросов"><Refresh size={16} /></MaterialButton>
    </div>
    <SlidingSegments className="timeline-filter-pills request-log-categories" role="tablist" value={category} aria-label="Категории вызовов LLM">
      {categories.map(item => <MaterialButton key={item.id} appearance="plain" materialKey={`requests.category.${item.id}`}
        role="tab" aria-label={item.label} aria-selected={category === item.id} tabIndex={category === item.id ? 0 : -1}
        id={`${id}-tab-${item.id}`} aria-controls={`${id}-entries`} className={`timeline-filter-pill${category === item.id ? " active" : ""}`} onClick={() => onCategory(item.id)}>
        {SHORT_CATEGORIES[item.id] || item.label}
      </MaterialButton>)}
    </SlidingSegments>
    <div className="request-log-filters">
      <div className="request-log-purpose" role="group" aria-label="Фильтр по назначению">
        <label htmlFor={`${id}-purpose`}>Назначение</label>
        <CustomSelect id={`${id}-purpose`} value={purpose} onChange={event => onPurpose(event.target.value)}>
          <option value="">{category === "all" ? "Все операции" : "Все в категории"}</option>
          {purposeOptions.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
        </CustomSelect>
      </div>
      {filtered && <MaterialButton appearance="plain" materialKey="requests.clear-filters" className="request-log-clear" onClick={onClearFilters}>Сбросить фильтры</MaterialButton>}
      <p className="request-log-cache-note">Кэш — часть входящих токенов</p>
    </div>
    <div id={`${id}-entries`} className="request-log-results" role="tabpanel" aria-labelledby={`${id}-tab-${category}`} aria-busy={loading}>
      {loading ? <div className="request-log-loading" role="status"><span>Загрузка запросов…</span>
        <div className="request-log-skeleton" aria-hidden="true">{[0, 1, 2].map(index => <div key={index}><span /><span /><span /></div>)}</div>
      </div> : error ? <div className="request-log-state" role="alert"><AlertTriangle size={24} /><strong>Не удалось загрузить запросы</strong><p>{error}</p>
        <MaterialButton materialKey="requests.retry" className="secondary" onClick={onRefresh}>Попробовать снова</MaterialButton>
      </div> : !items.length ? <div className="request-log-state" role="status"><Activity size={24} />
        <strong>{filtered ? "По этому фильтру запросов нет" : "Запросов пока нет"}</strong>
        <p>{filtered ? "Выберите другое назначение или категорию." : "Здесь появятся обращения Iris к модели."}</p>
      </div> : <ul className="request-log-list" aria-label="Запросы к модели">
        {items.map((record, index) => {
          const date = new Date(record.timestamp * 1000);
          const label = purposeLabels[record.purpose] || record.purpose;
          const success = record.status === "success";
          return <li key={`${record.request_id}-${index}`} className="request-log-item">
            <MaterialButton appearance="quiet" materialKey={`requests.record.${record.request_id}.${index}`} className="request-log-row"
              onClick={() => onInspect(record)} title="Подробности запроса"
              aria-label={`Открыть запрос: ${label}, ${fullDateFormat.format(date)}, ${record.model}, ${record.usage_available ? `${formatTokens(record.total)} токенов` : "расход не учтён"}, ${success ? "успешно" : "ошибка"}, ${latency(record.latency_ms)}`}>
              <span className="request-log-identity"><strong>{label}</strong><span className="request-log-meta">
                <time dateTime={date.toISOString()} title={fullDateFormat.format(date)}>{timeFormat.format(date)}<span> · {dayFormat.format(date)}</span></time>
                <span className="request-log-model" data-i18n-skip>{record.model}</span>
              </span></span>
              <span className="request-log-total"><strong>{counted(record, record.total)}</strong><span>{record.usage_available ? "всего токенов" : "не учтены"}</span></span>
              <span className="request-log-token-detail">
                <span>Вход <b>{counted(record, record.prompt)}</b></span><span>Ответ <b>{counted(record, record.completion)}</b></span>
                <span>Кэш <b>{counted(record, record.cache_hit)}</b></span>
              </span>
              <span className="request-log-outcome"><span className={`request-log-status ${success ? "" : "is-error"}`}>
                {success ? <Check size={13} /> : <AlertTriangle size={13} />}{success ? "Успешно" : "Ошибка"}</span>
                <span title={`${record.latency_ms.toLocaleString("ru-RU")} мс`}>{latency(record.latency_ms)}</span>
              </span>
              <ChevronRight size={18} className="request-log-arrow" aria-hidden="true" />
            </MaterialButton>
          </li>;
        })}
      </ul>}
    </div>
    {!error && records && records.total > 0 && <footer className="request-log-pagination">
      <p>{loading ? "Загружаем…" : <>{formatTokens(page * pageSize + 1)}–{formatTokens(Math.min(page * pageSize + items.length, records.total))} <span>из {formatTokens(records.total)}</span></>}</p>
      {totalPages > 1 && <div><MaterialButton appearance="quiet" materialKey="requests.previous" className="request-log-page-button"
        aria-label="Предыдущая страница запросов" disabled={loading || page === 0} onClick={() => onPage(page - 1)}><ChevronLeft size={17} /></MaterialButton>
        <span aria-live="polite">{page + 1} <span>/ {totalPages}</span></span>
        <MaterialButton appearance="quiet" materialKey="requests.next" className="request-log-page-button"
          aria-label="Следующая страница запросов" disabled={loading || page >= totalPages - 1} onClick={() => onPage(page + 1)}><ChevronRight size={17} /></MaterialButton>
      </div>}
    </footer>}
  </section>;
}

export function RequestRecordDetails({ record, label, copied, onCopy }: { record: TokenRecordItem; label: string; copied: boolean; onCopy: () => void }) {
  return <div className="request-record-details">
    <dl className="request-detail-meta">
      <div><dt>Назначение</dt><dd>{label}</dd></div>
      <div><dt>Модель</dt><dd data-i18n-skip>{record.model}</dd></div>
      <div><dt>Время</dt><dd>{fullDateFormat.format(new Date(record.timestamp * 1000))}</dd></div>
      <div><dt>Результат</dt><dd className={record.status === "success" ? "" : "request-detail-error"}>{record.status === "success" ? "Успешно" : "Ошибка"}</dd></div>
    </dl>
    <dl className="request-detail-numbers">
      <div><dt>Всего токенов</dt><dd>{counted(record, record.total)}</dd></div>
      <div><dt>Время ответа</dt><dd>{latency(record.latency_ms)}</dd></div>
      <div><dt>Входящие</dt><dd>{counted(record, record.prompt)}</dd></div>
      <div><dt>Ответы Iris</dt><dd>{counted(record, record.completion)}</dd></div>
      <div><dt>Из кэша</dt><dd>{counted(record, record.cache_hit)}</dd></div>
      {record.reasoning > 0 && <div><dt>Размышления</dt><dd>{counted(record, record.reasoning)}</dd></div>}
    </dl>
    <p className="request-detail-note">{record.usage_available ? "Токены из кэша уже включены во входящие." : "Модель не передала расход токенов для этого запроса."}</p>
    {record.error_type && <p className="request-detail-error" data-i18n-skip>{record.error_type}</p>}
    <Disclosure key={record.request_id} materialKey={`requests.json.${record.request_id}`} label="JSON записи" regionLabel="JSON запроса">
      <div className="request-detail-json">
        <MaterialButton materialKey="requests.copy-json" className="secondary" onClick={onCopy}>
          {copied ? <Check size={14} /> : <Copy size={14} />}<span>{copied ? "Скопировано!" : "Копировать JSON"}</span>
        </MaterialButton>
        <pre data-i18n-skip><code>{JSON.stringify(record, null, 2)}</code></pre>
      </div>
    </Disclosure>
  </div>;
}
