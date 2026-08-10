import { Suspense, lazy } from "react";

const IrisAvatarCanvas = lazy(async () => ({
  default: (await import("../avatar/IrisAvatarCanvas")).IrisAvatarCanvas,
}));

/** The heavy WebGL renderer is fetched only when the chat host is visible. */
export function InAppAvatarHost() {
  return <Suspense fallback={<aside className="in-app-avatar-stage" aria-label="Загрузка аватара Iris" />}>
    <IrisAvatarCanvas />
  </Suspense>;
}
