import React, { useEffect, useState } from "react";
import ReactDOM from "react-dom/client";
import { ChangelogDialog, ChangelogSettingsCard } from "./components/Changelog";
import { MaterialButtonContours } from "./components/MaterialButtonContours";
import { MaterialButton } from "./components/MaterialButton";
import { NotificationHost } from "./components/NotificationHost";
import { notify } from "./notifications";
import { APP_VERSION, currentRelease } from "./changelog/catalog";
import "./tokens.css";
import "./styles.css";
import "./components/MaterialButton.css";
import "./components/FieldMaterial.css";
import "./product-improvements.css";

// Authoring preview only; excluded from the default product build.
function Preview() {
  const [open, setOpen] = useState(true);
  useEffect(() => {
    const show = () => setOpen(true);
    window.addEventListener("iris-open-changelog", show);
    return () => window.removeEventListener("iris-open-changelog", show);
  }, []);
  return <>
    <MaterialButtonContours />
    <main style={{ maxWidth: 760, padding: 32, margin: "44px auto" }}>
      <h1 style={{ fontSize: 24 }}>Просмотр заметок об обновлении</h1>
      <p style={{ color: "var(--color-text-soft)", lineHeight: 1.7 }}>Редакторский просмотр текущей записи. Подключение к ядру не требуется.</p>
      <ChangelogSettingsCard />
      <MaterialButton materialKey="changelog.preview.notice" type="button" className="secondary" style={{ marginTop: 24 }} onClick={() => notify.info(`Что нового в Iris · ${APP_VERSION}`, currentRelease.summary, { id: "changelog.preview", duration: "persistent", navigateView: "changelog", navigateLabel: "Что нового" })}>Показать уведомление</MaterialButton>
    </main>
    <ChangelogDialog open={open} onClose={() => setOpen(false)} />
    <NotificationHost onNavigate={() => setOpen(true)} />
  </>;
}

ReactDOM.createRoot(document.getElementById("root")!).render(<React.StrictMode><Preview /></React.StrictMode>);
