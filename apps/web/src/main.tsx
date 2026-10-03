import React from "react";
import ReactDOM from "react-dom/client";

import App from "./App";
import { MaterialButtonContours } from "./components/MaterialButtonContours";
import "./fonts/proxima-nova.css";
import "./tokens.css";
import "./styles.css";
import "./components/MaterialButton.css";
import "./components/FieldMaterial.css";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <MaterialButtonContours />
    <App />
  </React.StrictMode>,
);

// The inline splash covers the parsing gap before React mounts. Remove it
// after handing the root to React so it cannot remain underneath the app.
document.querySelector(".iris-static-splash")?.remove();
