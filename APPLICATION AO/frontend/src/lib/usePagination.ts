import { useEffect, useState } from "react";

import { api } from "../api/client";

interface Page<T> {
  total: number;
  resultats: T[];
}

/**
 * Charge une liste paginée (« Afficher plus ») : la première page à chaque
 * changement de filtres, puis les suivantes à la demande.
 */
export function usePagination<T, P extends Page<T>>(chemin: string) {
  const [premiere, setPremiere] = useState<P | null>(null);
  const [suite, setSuite] = useState<T[]>([]);
  const [page, setPage] = useState(1);
  const [chargement, setChargement] = useState(true);
  const [erreur, setErreur] = useState<string | null>(null);

  useEffect(() => {
    let actif = true;
    setChargement(true);
    setSuite([]);
    setPage(1);
    api<P>(`${chemin}&page=1`)
      .then((resultat) => {
        if (!actif) return;
        setPremiere(resultat);
        setErreur(null);
      })
      .catch((probleme: unknown) => {
        if (actif) setErreur(probleme instanceof Error ? probleme.message : "Erreur inconnue");
      })
      .finally(() => {
        if (actif) setChargement(false);
      });
    return () => {
      actif = false;
    };
  }, [chemin]);

  async function afficherPlus() {
    const suivante = page + 1;
    setChargement(true);
    try {
      const resultat = await api<P>(`${chemin}&page=${suivante}`);
      setSuite((elements) => [...elements, ...resultat.resultats]);
      setPage(suivante);
    } catch (probleme) {
      setErreur(probleme instanceof Error ? probleme.message : "Erreur inconnue");
    } finally {
      setChargement(false);
    }
  }

  const elements = premiere ? [...premiere.resultats, ...suite] : [];
  return {
    donnees: premiere,
    elements,
    total: premiere?.total ?? 0,
    reste: premiere ? premiere.total - elements.length : 0,
    chargement,
    erreur,
    afficherPlus,
  };
}
