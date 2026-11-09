import { BrowserRouter, Navigate, Route, Routes } from "react-router";

import { FournisseurAuth } from "./auth/AuthContext";
import Layout from "./components/Layout";
import RouteProtegee from "./components/RouteProtegee";
import Articles from "./pages/Articles";
import Bibliotheque from "./pages/Bibliotheque";
import Connexion from "./pages/Connexion";
import LotEditeur from "./pages/LotEditeur";
import PieceEditeur from "./pages/PieceEditeur";
import Prix from "./pages/Prix";
import ProjetDetail from "./pages/ProjetDetail";
import Projets from "./pages/Projets";
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
            <Route path="projets" element={<Projets />} />
            <Route path="projets/:projetId" element={<ProjetDetail />} />
            <Route path="projets/:projetId/lots/:lotId" element={<LotEditeur />} />
            <Route path="projets/:projetId/pieces/:pieceId" element={<PieceEditeur />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </FournisseurAuth>
    </BrowserRouter>
  );
}
