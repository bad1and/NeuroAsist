// Native initialization sets the view before parsing. Clear the document
// canvas before the first paint, including while the React bundle loads.
if (window.__IRIS_VIEW__ === "desktop-avatar") {
  document.documentElement.classList.add("desktop-avatar-root");
}
