import { useId } from "react";
import { IconInterfaceCross, IconInterfacePlus, IconInterfaceSearch, IconInterfaceSpirals } from "../CustomIcons";
import { MaterialButton } from "./MaterialButton";

type Props = {
  materialKey: string;
  query: string;
  onQueryChange: (query: string) => void;
  searchLabel: string;
  placeholder: string;
  refreshLabel: string;
  onRefresh: () => void;
  onAdd: () => void;
  busy: boolean;
  addDisabled?: boolean;
  count?: string;
};

/** The collection tabs share the saved-memory search surface and controls. */
export function MemoryCollectionToolbar({ materialKey, query, onQueryChange, searchLabel, placeholder, refreshLabel, onRefresh, onAdd, busy, addDisabled, count }: Props) {
  const searchId = useId();
  return <header className="memory-heading memory-collection-heading">
    <div className="memory-toolbar">
      <form className="search-form compact" role="search" aria-label={searchLabel} onSubmit={event => {
        event.preventDefault();
        document.getElementById(searchId)?.focus();
      }}>
        <input id={searchId} aria-label={searchLabel} placeholder={placeholder} value={query} onChange={event => onQueryChange(event.target.value)} />
        {query && <MaterialButton materialKey={`${materialKey}.clear`} appearance="quiet" type="button" className="search-clear-btn" aria-label="Очистить" onClick={() => {
          onQueryChange("");
          document.getElementById(searchId)?.focus();
        }}><IconInterfaceCross size={12} aria-hidden="true" /></MaterialButton>}
        <MaterialButton materialKey={`${materialKey}.refresh`} appearance="quiet" type="button" className="icon-button" aria-label={refreshLabel} title={refreshLabel} disabled={busy} onClick={onRefresh}><IconInterfaceSpirals size={17} aria-hidden="true" /></MaterialButton>
        <MaterialButton materialKey={`${materialKey}.search`} appearance="quiet" type="submit" className="icon-button search-submit" aria-label={searchLabel} title={searchLabel}><IconInterfaceSearch size={17} aria-hidden="true" /></MaterialButton>
      </form>
    </div>
    <div className="memory-collection-actions">
      {count && <span className="memory-collection-count" data-i18n-skip>{count}</span>}
      <MaterialButton materialKey={`${materialKey}.add`} className="primary-button memory-add-button" type="button" disabled={busy || addDisabled} onClick={onAdd}><IconInterfacePlus size={16} aria-hidden="true" />Добавить</MaterialButton>
    </div>
  </header>;
}
