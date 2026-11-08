import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router";

import { useAuth } from "../auth/AuthContext";

export default function RouteProtegee({ children }: { children: ReactNode }) {
  const { utilisateur, chargement } = useAuth();
  const emplacement = useLocation();

  if (chargement) {
    return (
      <div className="grid min-h-screen place-items-center text-attenue" role="status">
        Chargement…
      </div>
    );
  }
  if (!utilisateur) {
    return <Navigate to="/connexion" replace state={{ depuis: emplacement.pathname + emplacement.search }} />;
  }
  return <>{children}</>;
}
