import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import "./index.css";
import App from "./App.tsx";
import { initTheme } from "./lib/theme-toggle";

// Stamp data-theme on <html> before React renders — the first paint is
// already in the visitor's stored (or OS) theme, so no light-mode flash.
initTheme();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
