/** Portail des intervenants (entreprises, MOE associée, MOA, CT, CSPS, OPC) : application séparée,
 * seule servie sur l'adresse Internet de la GED. */
import "@fontsource-variable/inter/index.css";
import "@fontsource/space-grotesk/500.css";
import "@fontsource/space-grotesk/600.css";
import "@fontsource/space-grotesk/700.css";
import "../index.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import Portail from "./Portail";

createRoot(document.getElementById("racine")!).render(
  <StrictMode>
    <Portail />
  </StrictMode>,
);
