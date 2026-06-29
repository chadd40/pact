import React from "react";
import ReactDOM from "react-dom/client";
import { createHashRouter, Navigate, RouterProvider } from "react-router-dom";
import "./styles.css";
import "./components.css";
import "./redesign.css";
import "./screens/app.css";
import { App } from "./App";
import { AppShell } from "./components/AppShell";
import { RootEntry } from "./RootEntry";
import { Create } from "./screens/Create";
import { Onboard } from "./screens/Onboard";
import { Home } from "./screens/Home";
import { PactDetail } from "./screens/PactDetail";
import { Coach } from "./screens/Coach";
import { Charities } from "./screens/Charities";
import { Settings } from "./screens/Settings";
import { isDesktop } from "./lib/platform";

// The same SPA powers two surfaces. The public web funnel (GitHub Pages) exposes
// ONLY Landing + Create — it has no backend, so the in-app pages (dashboard,
// charities, coach, settings, onboard) would just 404 against /api. Those live
// only in the packaged desktop app, which runs the local sidecar. Any stray
// in-app URL on the web redirects back to the landing page.
const appChildren = isDesktop()
  ? [
      // Full-bleed, no app shell.
      { path: "/", element: <RootEntry /> },
      { path: "/create", element: <Create /> },
      { path: "/onboard", element: <Onboard /> },
      // In-app: persistent sidebar shell.
      {
        element: <AppShell />,
        children: [
          { path: "/dashboard", element: <Home /> },
          { path: "/pact/:pactId", element: <PactDetail /> },
          { path: "/coach", element: <Coach /> },
          { path: "/charities", element: <Charities /> },
          { path: "/settings", element: <Settings /> },
        ],
      },
    ]
  : [
      { path: "/", element: <RootEntry /> },
      { path: "/create", element: <Create /> },
      { path: "*", element: <Navigate to="/" replace /> },
    ];

const router = createHashRouter([{ element: <App />, children: appChildren }]);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>
);
