import React from "react";
import ReactDOM from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import "./styles.css";
import "./components.css";
import { App } from "./App";
import { Home } from "./screens/Home";
import { Create } from "./screens/Create";
import { Confirm } from "./screens/Confirm";
import { Active } from "./screens/Active";
import { VerdictScreen } from "./screens/Verdict";

const router = createBrowserRouter([
  {
    element: <App />,
    children: [
      { path: "/", element: <Home /> },
      { path: "/create", element: <Create /> },
      { path: "/confirm/:pactId", element: <Confirm /> },
      { path: "/pact/:pactId", element: <Active /> },
      { path: "/verdict/:pactId", element: <VerdictScreen /> },
    ],
  },
]);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>
);
