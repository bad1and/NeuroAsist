export type SearchFocus = { requestId: string; id: string; query: string; section?: "all" | "commitments" };
export type SearchDestination =
  | { kind: "history"; focus: SearchFocus }
  | { kind: "memory"; focus: SearchFocus }
  | { kind: "setting"; section: string; focusId?: string };

export { SETTINGS_SEARCH, searchSettings } from "./settings/registry";
