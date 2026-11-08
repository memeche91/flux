import { Search } from "lucide-react";
import type { ReactNode } from "react";

export const CLASSE_CHAMP = "min-h-11 w-full rounded-lg border border-bordure-forte bg-fond px-3 text-texte";

export function Champ({ id, libelle, children, large = false }: { id: string; libelle: string; children: ReactNode; large?: boolean }) {
  return (
    <div className={`flex min-w-0 flex-col gap-1.5 ${large ? "flex-[3_1_260px]" : "flex-[1_1_170px]"}`}>
      <label htmlFor={id} className="text-xs font-semibold text-attenue">
        {libelle}
      </label>
      {children}
    </div>
  );
}

export function ChampRecherche({
  id,
  libelle,
  valeur,
  surChangement,
  indication,
}: {
  id: string;
  libelle: string;
  valeur: string;
  surChangement: (valeur: string) => void;
  indication: string;
}) {
  return (
    <Champ id={id} libelle={libelle} large>
      <div className="relative">
        <Search aria-hidden="true" className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-attenue" />
        <input
          id={id}
          type="search"
          value={valeur}
          onChange={(e) => surChangement(e.target.value)}
          placeholder={indication}
          className={`${CLASSE_CHAMP} pl-9`}
        />
      </div>
    </Champ>
  );
}

export function BoutonAfficherPlus({ reste, chargement, surClic }: { reste: number; chargement: boolean; surClic: () => void }) {
  if (reste <= 0) return null;
  return (
    <button
      type="button"
      onClick={surClic}
      disabled={chargement}
      className="mx-auto min-h-11 rounded-lg border border-bordure-forte px-5 font-semibold text-texte hover:bg-surface-2 disabled:opacity-50"
    >
      {chargement ? "Chargement…" : `Afficher plus (${reste.toLocaleString("fr-FR")} restants)`}
    </button>
  );
}

/** Applique une saisie après une courte pause (évite une requête par touche). */
export function delaiSaisie(callback: () => void, delai = 250) {
  const minuterie = window.setTimeout(callback, delai);
  return () => window.clearTimeout(minuterie);
}
