import { Disclosure } from "./Disclosure";
import { MaterialButton } from "./MaterialButton";
import { IconInterfaceActivity } from "../CustomIcons";
import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { getLlmTokenStats, getLlmTokenRecords, resetLlmTokenStats } from "../api";
import { AppDialog } from "./AppDialog";
import { ExpenseDashboard } from "./ExpenseDashboard";
import { RequestJournal, RequestRecordDetails } from "./RequestJournal";
import type { TokenUsageStats, TokenRecordItem, TokenRecordsResponse } from "../types";

const PURPOSE_LABELS: Record<string, string> = {
  chat_json: "Диалог (JSON)",
  chat_live: "Голосовой стрим",
  chat: "Чат / Диалог",
  live: "Живой разговор",
  chat_json_repair: "Диалог (Repair JSON)",
  chat_json_guard_retry: "Диалог (Guard Retry)",
  chat_live_guard_retry: "Голос (Guard Retry)",
  memory: "Извлечение памяти",
  memory_extraction: "Извлечение памяти",
  memory_repair: "Память (Repair JSON)",
  reflection: "Рефлексия и дневник",
  reflection_repair: "Рефлексия (Repair JSON)",
  memory_synthesis: "Синтез профиля",
  memory_conflict: "Разрешение конфликтов",
  adjudication: "Арбитраж диалога",
  coding: "Coding Agent",
  test: "Тестирование",
};

export type PurposeCategory = "all" | "chat" | "memory" | "guards" | "coding";

export const CATEGORY_TABS: { id: PurposeCategory; label: string; purposes?: string[] }[] = [
  { id: "all", label: "Все назначения" },
  { id: "chat", label: "Диалог и голос", purposes: ["chat_json", "chat_live", "adjudication", "chat", "live"] },
  { id: "memory", label: "Память и рефлексия", purposes: ["memory", "reflection", "memory_extraction", "memory_synthesis", "memory_conflict"] },
  { id: "guards", label: "Проверки и исправления", purposes: ["chat_json_repair", "chat_json_guard_retry", "chat_live_guard_retry", "memory_repair", "reflection_repair"] },
  { id: "coding", label: "Coding Agent", purposes: ["coding"] },
];

export function TokenAnalyticsSettings() {
  const [timeframe, setTimeframe] = useState<"24h" | "7d" | "30d" | "all">("24h");
  const [stats, setStats] = useState<TokenUsageStats | null>(null);
  const [recordsResponse, setRecordsResponse] = useState<TokenRecordsResponse | null>(null);
  const [selectedCategory, setSelectedCategory] = useState<PurposeCategory>("all");
  const [purposeFilter, setPurposeFilter] = useState<string>("");
  const [page, setPage] = useState(0);
  const pageSize = 20;
  const journalRef = useRef<HTMLDivElement>(null);
  const [journalOpen, setJournalOpen] = useState(false);
  const statsRequest = useRef(0);
  const recordsRequest = useRef(0);

  const [loading, setLoading] = useState(true);
  const [recordsLoading, setRecordsLoading] = useState(false);
  const [recordsError, setRecordsError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Modals & Details
  const [showResetDialog, setShowResetDialog] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [inspectRecord, setInspectRecord] = useState<TokenRecordItem | null>(null);
  const [copiedInspect, setCopiedInspect] = useState(false);

  const currentCategory = useMemo(
    () => CATEGORY_TABS.find((c) => c.id === selectedCategory),
    [selectedCategory],
  );

  const effectivePurpose = useMemo(() => {
    if (purposeFilter) return purposeFilter;
    if (currentCategory?.purposes) return currentCategory.purposes.join(",");
    return "";
  }, [purposeFilter, currentCategory]);

  const availablePurposes = useMemo(() => {
    if (!currentCategory?.purposes) {
      return Object.entries(PURPOSE_LABELS);
    }
    return Object.entries(PURPOSE_LABELS).filter(([k]) => currentCategory.purposes?.includes(k));
  }, [currentCategory]);

  const fetchStats = useCallback(async (tf = timeframe) => {
    const request = ++statsRequest.current;
    setStats(previous => previous?.timeframe === tf ? previous : null);
    setLoading(true);
    setError(null);
    try {
      const data = await getLlmTokenStats(tf);
      if (request === statsRequest.current) setStats(data);
    } catch (err) {
      if (request === statsRequest.current) setError(err instanceof Error ? err.message : "Не удалось загрузить статистику токенов");
    } finally {
      if (request === statsRequest.current) setLoading(false);
    }
  }, [timeframe]);

  const fetchRecords = useCallback(async (currPage = page, purpose = effectivePurpose) => {
    const request = ++recordsRequest.current;
    setRecordsLoading(true);
    setRecordsError(null);
    try {
      const data = await getLlmTokenRecords(pageSize, currPage * pageSize, purpose || undefined);
      if (request === recordsRequest.current) setRecordsResponse(data);
    } catch (err) {
      if (request === recordsRequest.current) setRecordsError(err instanceof Error ? err.message : "Не удалось загрузить журнал запросов");
    } finally {
      if (request === recordsRequest.current) setRecordsLoading(false);
    }
  }, [page, effectivePurpose]);

  useEffect(() => {
    void fetchStats(timeframe);
  }, [fetchStats, timeframe]);

  useEffect(() => {
    void fetchRecords(page, effectivePurpose);
  }, [fetchRecords, page, effectivePurpose]);

  const handleReset = async () => {
    setResetting(true);
    try {
      await resetLlmTokenStats();
      setShowResetDialog(false);
      await fetchStats();
      await fetchRecords(0, effectivePurpose);
      setPage(0);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось сбросить статистику");
    } finally {
      setResetting(false);
    }
  };

  const handleCopyInspectJson = async () => {
    if (!inspectRecord) return;
    try {
      await navigator.clipboard.writeText(JSON.stringify(inspectRecord, null, 2));
      setCopiedInspect(true);
      setTimeout(() => setCopiedInspect(false), 2000);
    } catch {
      // Fallback
    }
  };

  return (
    <div className="token-analytics-page">
      <ExpenseDashboard stats={stats?.timeframe === timeframe ? stats : null} loading={loading} error={error} timeframe={timeframe}
        onTimeframe={setTimeframe} onRefresh={() => { void fetchStats(); void fetchRecords(); }}
        onReset={() => setShowResetDialog(true)} purposeLabels={PURPOSE_LABELS}
        onPurpose={purpose => {
          setSelectedCategory("all");
          setPurposeFilter(purpose);
          setPage(0);
          const journal = journalRef.current;
          setJournalOpen(true);
          journal?.scrollIntoView?.({ behavior: "instant", block: "start" });
        }} />

      <Disclosure materialKey="requests.journal" label="Подробный журнал запросов" ref={journalRef}
        open={journalOpen} onOpenChange={setJournalOpen} className="settings-technical-details expense-journal" regionLabel="Журнал запросов">
        <RequestJournal records={recordsResponse} loading={recordsLoading} error={recordsError} visible={journalOpen}
          categories={CATEGORY_TABS} category={selectedCategory} purpose={purposeFilter} purposeOptions={availablePurposes}
          purposeLabels={PURPOSE_LABELS} page={page} pageSize={pageSize} onPage={setPage}
          onCategory={category => { setSelectedCategory(category); setPurposeFilter(""); setPage(0); }}
          onPurpose={purpose => { setPurposeFilter(purpose); setPage(0); }}
          onClearFilters={() => { setSelectedCategory("all"); setPurposeFilter(""); setPage(0); }}
          onRefresh={() => { void fetchRecords(); }}
          onInspect={record => { setCopiedInspect(false); setInspectRecord(record); }} />
      </Disclosure>

      {/* Inspect Raw JSON Dialog */}
      <AppDialog
        open={Boolean(inspectRecord)}
        title="Подробности запроса"
        icon={<IconInterfaceActivity size={20} />}
        size="wide"
        className="request-inspect-dialog"
        description={inspectRecord ? `Запрос: ${inspectRecord.request_id}` : ""}
        onClose={() => setInspectRecord(null)}
        variant="info"
      >
        <div className="inspect-dialog-body">
          {inspectRecord && <RequestRecordDetails record={inspectRecord}
            label={PURPOSE_LABELS[inspectRecord.purpose] || inspectRecord.purpose}
            copied={copiedInspect} onCopy={() => { void handleCopyInspectJson(); }} />}
          <div className="dialog-actions" style={{ marginTop: 16 }}>
            <MaterialButton materialKey={"TokenAnalyticsSettings.button-9"}
              type="button"
              className="secondary"
              onClick={() => setInspectRecord(null)}
            >
              Закрыть
            </MaterialButton>
          </div>
        </div>
      </AppDialog>

      {/* Reset Confirmation Dialog */}
      <AppDialog
        open={showResetDialog}
        title="Сбросить статистику токенов?"
        description="Вся накопленная статистика, история запросов и данные о расходах будут безвозвратно удалены из базы данных."
        onClose={() => !resetting && setShowResetDialog(false)}
        variant="danger"
      >
        <div className="dialog-actions">
          <MaterialButton materialKey={"TokenAnalyticsSettings.button-10"}
            type="button"
            className="secondary"
            disabled={resetting}
            onClick={() => setShowResetDialog(false)}
          >
            Отмена
          </MaterialButton>
          <MaterialButton materialKey={"TokenAnalyticsSettings.button-11"}
            type="button"
            className="danger-button"
            disabled={resetting}
            onClick={() => void handleReset()}
          >
            {resetting ? "Удаление…" : "Сбросить все данные токенов"}
          </MaterialButton>
        </div>
      </AppDialog>
    </div>
  );
}
