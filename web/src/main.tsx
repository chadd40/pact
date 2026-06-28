import React from "react";
import ReactDOM from "react-dom/client";
import { createHashRouter, RouterProvider, Navigate } from "react-router-dom";
import "./styles.css";
import "./components.css";
import "./redesign.css";
import "./screens/app.css";
import { App } from "./App";
import { AppShell } from "./components/AppShell";
import { Landing } from "./screens/Landing";
import { Create } from "./screens/Create";
import { Onboard } from "./screens/Onboard";
import { Home } from "./screens/Home";
import { PactDetail } from "./screens/PactDetail";
import { Coach } from "./screens/Coach";
import { Charities } from "./screens/Charities";
import { Settings } from "./screens/Settings";
import { isDesktop } from "./lib/platform";
import { api } from "./api";
import { getLocalOwner } from "./owner";

function RootEntry() {
  const [dest, setDest] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (!isDesktop()) { setDest("__web__"); return; }
    // Desktop: first-run owners start in Create; returning owners go to the dashboard.
    api.listPacts(getLocalOwner())
      .then((pacts) => setDest(pacts.length > 0 ? "/dashboard" : "/create"))
      .catch(() => setDest("/create"));
  }, []);
  if (dest === null) return null;            // brief: waiting on listPacts
  if (dest === "__web__") return <Landing />;
  return <Navigate to={dest} replace />;
}

const router = createHashRouter([
  {
    element: <App />,
    children: [
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
    ],
  },
]);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>
);
