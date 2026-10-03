import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "../fonts/proxima-nova.css";
import "../tokens.css";
import "../components/MaterialButton.css";
import "./design-pack.css";
import { DesignPack } from "./DesignPack";
import { MaterialButtonContours } from "../components/MaterialButtonContours";

createRoot(document.getElementById("root")!).render(<StrictMode><MaterialButtonContours /><DesignPack /></StrictMode>);
