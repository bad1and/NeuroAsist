import React from "react";
import ReactDOM from "react-dom/client";

import App from "./App";
import { MaterialButtonContours } from "./components/MaterialButtonContours";
import "./tokens.css";
import "./styles.css";
import "./components/StartupScreen.css";
import "./components/MaterialButton.css";
import "./components/FieldMaterial.css";
import "./product-improvements.css";
import "./components/StatusBadge.css";
import "./animations/motion.css";
import "./overview.css";
import "./settings/settings.css";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <MaterialButtonContours />
    <App />
  </React.StrictMode>,
);

// React replaces the static seed during its first commit. Keep it visible
// until then, including while the initial module graph is being parsed.
