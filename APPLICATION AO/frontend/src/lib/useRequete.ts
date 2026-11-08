import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";

/** Charge une ressource de l'API et permet de la recharger (après un ajout, par ex.). */
export function useRequete<T>(chemin: string) {
  const [donnees, setDonnees] = useState<T | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let actif = true;
    api<T>(chemin)
      .then((resultat) => {
        if (!actif) return;
        setDonnees(resultat);
        setErreur(null);
      })
      .catch((probleme: unknown) => {
        if (actif) setErreur(probleme instanceof Error ? probleme.message : "Erreur inconnue");
      });
    return () => {
      actif = false;
    };
  }, [chemin, version]);

  const recharger = useCallback(() => setVersion((v) => v + 1), []);

  return { donnees, erreur, recharger };
}
