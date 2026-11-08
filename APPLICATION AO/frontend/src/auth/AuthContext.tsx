import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { api, EVENEMENT_SESSION_EXPIREE } from "../api/client";
import type { Utilisateur } from "../api/types";

interface ValeurAuth {
  utilisateur: Utilisateur | null;
  chargement: boolean;
  connexion: (identifiant: string, motDePasse: string) => Promise<void>;
  deconnexion: () => Promise<void>;
}

const ContexteAuth = createContext<ValeurAuth | null>(null);

export function FournisseurAuth({ children }: { children: ReactNode }) {
  const [utilisateur, setUtilisateur] = useState<Utilisateur | null>(null);
  const [chargement, setChargement] = useState(true);

  useEffect(() => {
    api<Utilisateur>("/auth/moi")
      .then(setUtilisateur)
      .catch(() => setUtilisateur(null))
      .finally(() => setChargement(false));

    const surExpiration = () => setUtilisateur(null);
    window.addEventListener(EVENEMENT_SESSION_EXPIREE, surExpiration);
    return () => window.removeEventListener(EVENEMENT_SESSION_EXPIREE, surExpiration);
  }, []);

  const connexion = useCallback(async (identifiant: string, motDePasse: string) => {
    const resultat = await api<Utilisateur>("/auth/connexion", {
      method: "POST",
      body: JSON.stringify({ identifiant, mot_de_passe: motDePasse }),
    });
    setUtilisateur(resultat);
  }, []);

  const deconnexion = useCallback(async () => {
    try {
      await api("/auth/deconnexion", { method: "POST" });
    } finally {
      setUtilisateur(null);
    }
  }, []);

  const valeur = useMemo(
    () => ({ utilisateur, chargement, connexion, deconnexion }),
    [utilisateur, chargement, connexion, deconnexion],
  );

  return <ContexteAuth.Provider value={valeur}>{children}</ContexteAuth.Provider>;
}

export function useAuth(): ValeurAuth {
  const valeur = useContext(ContexteAuth);
  if (!valeur) throw new Error("useAuth doit être utilisé dans <FournisseurAuth>.");
  return valeur;
}
