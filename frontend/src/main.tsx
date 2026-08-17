import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { MuiProviders } from "./theme/MuiProviders";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <MuiProviders>
      <App />
    </MuiProviders>
  </React.StrictMode>,
);
