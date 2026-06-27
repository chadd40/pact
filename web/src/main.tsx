import React from "react";
import ReactDOM from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import "./styles.css";
import "./components.css";
import "./redesign.css";
import { App } from "./App";
import { Dashboard } from "./screens/Dashboard";
import { Create } from "./screens/Create";
import { PactView } from "./screens/Pact";

const router = createBrowserRouter([
  {
    element: <App />,
    children: [
      { path: "/", element: <Dashboard /> },
      { path: "/create", element: <Create /> },
      { path: "/pact/:pactId", element: <PactView /> },
    ],
  },
]);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>
);
