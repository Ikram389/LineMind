import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

// The one font, self-hosted (no request to a font service).
import "@fontsource-variable/inter";

import App from "./App.tsx";
import "./index.css";

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("Root element #root not found");
}

createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
