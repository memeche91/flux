import { BrowserRouter, Navigate, Route, Routes } from "react-router";

import { FournisseurAuth } from "./auth/AuthContext";
import Layout from "./components/Layout";
import RouteProtegee from "./components/RouteProtegee";
import Articles from "./pages/Articles";
import Bibliotheque from "./pages/Bibliotheque";
import Connexion from "./pages/Connexion";
import Prix from "./pages/Prix";
import TableauDeBord from "./pages/TableauDeBord";

export default function App() {
  return (
    <BrowserRouter>
      <FournisseurAuth>
        <Routes>
          <Route path="/connexion" element={<Connexion />} />
          <Route
            element={
              <RouteProtegee>
                <Layout />
              </RouteProtegee>
            }
          >
            <Route index element={<TableauDeBord />} />
            <Route path="bibliotheque" element={<Bibliotheque />} />
            <Route path="articles" element={<Articles />} />
            <Route path="prix" element={<Prix />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </FournisseurAuth>
    </BrowserRouter>
  );
}
