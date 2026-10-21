// Development-only visual review. No backend connection or saved state.
import { useState } from "react";
import { createRoot } from "react-dom/client";
import { IrisMoodOrb } from "./components/IrisMoodOrb";
import { MaterialButton } from "./components/MaterialButton";
import { MaterialButtonContours } from "./components/MaterialButtonContours";
import { AppCheckbox } from "./components/AppCheckbox";
import { getMoodVisuals } from "./mood-visuals";
import "./tokens.css";
import "./styles.css";
import "./state.css";
import "./components/MaterialButton.css";

function MoodPreview() {
  const [emotion, setEmotion] = useState("neutral");
  const [strength, setStrength] = useState("moderate");
  const [causes, setCauses] = useState(false);
  return <main style={{ maxWidth: 760, margin: "64px auto", padding: 24 }}>
    <h1 style={{ fontSize: 24 }}>Настроение Iris</h1>
    <p style={{ color: "var(--color-text-muted)", margin: "12px 0 32px" }}>Предпросмотр плашки · состояние Iris не меняется</p>
    <div className="state-dashboard" style={{ height: "auto", minHeight: 0 }}>
      <div className="state-sidebar-panels" style={{ width: 330, maxWidth: "calc(100% + 40px)", flex: "none", overflow: "visible" }}>
      <div className="state-hero-card mood-card">
        <IrisMoodOrb emotion={emotion} strength={strength} variant="surface" />
        <div className="mood-visual"><div className="mood-info"><h2>{getMoodVisuals(emotion).labelRu}</h2></div></div>
        {causes && <div className="mood-causes">
          <div className="mood-causes-heading"><h4>Что влияет на настроение</h4><span className="cause-group-total">2</span></div>
          <ul><li><div className="cause-copy"><strong>Поддержка</strong><span>Влияет сейчас</span></div></li>
            <li><div className="cause-copy"><strong>Шутка / Подкол</strong><span>Затихает</span></div></li></ul>
        </div>}
      </div>
      </div>
    </div>
    <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 32 }}>
      {["neutral", "joy", "sadness", "anger", "anxiety", "affection", "thinking", "playfulness", "fatigue", "confusion"].map(key =>
        <MaterialButton key={key} materialKey={`mood-preview.${key}`} tone={emotion === key ? "accent" : "graphite"} className="secondary" type="button" aria-pressed={emotion === key} onClick={() => setEmotion(key)}>{getMoodVisuals(key).labelRu}</MaterialButton>)}
    </div>
    <div style={{ display: "flex", flexWrap: "wrap", gap: 16, marginTop: 24, alignItems: "center" }}>
      <label>Выразительность <select value={strength} onChange={e => setStrength(e.target.value)}>
        <option value="subtle">Сдержанно</option><option value="moderate">Умеренно</option><option value="strong">Сильно</option>
      </select></label>
      <label style={{ display: "flex", gap: 8, alignItems: "center" }}><AppCheckbox checked={causes} onChange={e => setCauses(e.target.checked)} />С причинами</label>
    </div>
  </main>;
}

createRoot(document.getElementById("root")!).render(<><MaterialButtonContours /><MoodPreview /></>);
