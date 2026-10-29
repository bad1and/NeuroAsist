// Suppress the browser menu in every Iris view, including before React loads.
// Keep propagation and mouse/pointer events intact for application controls.
document.addEventListener("contextmenu", (event) => event.preventDefault(), { capture: true });
