import { Activity, startTransition, useEffect, useState, type ReactNode } from "react";
import { isTestEnvironment } from "../animations/core";
import { LoadingRing } from "./LoadingRing";

/** Keep drafts and scroll positions while suspending hidden screens' effects. */
export function WorkspaceView({ active, children }: { active: boolean; children: ReactNode }) {
  const [prepared, setPrepared] = useState(isTestEnvironment);
  useEffect(() => {
    if (!active || prepared) return;
    // Paint the indicator before rendering the first, potentially large screen.
    let frame = requestAnimationFrame(() => {
      frame = requestAnimationFrame(() => startTransition(() => setPrepared(true)));
    });
    return () => cancelAnimationFrame(frame);
  }, [active, prepared]);
  return <Activity mode={active ? "visible" : "hidden"}>
    <div className="workspace-view-slot" hidden={!active}>
      {prepared ? children : <LoadingRing className="page-loading" />}
    </div>
  </Activity>;
}
