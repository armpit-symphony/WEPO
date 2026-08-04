// CRITICAL: Enable polyfills for crypto libraries
import { Buffer } from 'buffer';
import process from 'process';

// Make polyfills available globally BEFORE any other imports
if (typeof window !== 'undefined') {
  window.Buffer = Buffer;
  window.process = process;
  window.global = window;
}

import React from "react";
import ReactDOM from "react-dom/client";
import "./index.css";
import App from "./App";

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
