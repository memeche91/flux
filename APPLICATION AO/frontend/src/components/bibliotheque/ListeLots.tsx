import type { Lot } from "../../api/types";
import { formaterNombre } from "../../lib/format";

interface Proprietes {
  lots: Lot[];
  comptes: Record<string, number>;
  lotSelectionne: number | null;
  surSelection: (lotId: number | null) => void;
}

/** Filtre par lot : liste latérale sur grand écran, menu déroulant sur téléphone et tablette. */
export default function ListeLots({ lots, comptes, lotSelectionne, surSelection }: Proprietes) {
  const total = Object.values(comptes).reduce((somme, n) => somme + n, 0);
  const elements: { id: number | null; code: string; intitule: string; nombre: number }[] = [
    { id: null, code: "", intitule: "Tous les lots", nombre: total },
    ...lots.map((lot) => ({ ...lot, nombre: comptes[String(lot.id)] ?? 0 })),
  ];

  return (
    <>
      <div className="flex w-full flex-col gap-1.5 lg:hidden">
        <label htmlFor="filtre-lot" className="text-xs font-semibold text-attenue">
          Afficher le lot
        </label>
        <select
          id="filtre-lot"
          value={lotSelectionne ?? ""}
          onChange={(e) => surSelection(e.target.value ? Number(e.target.value) : null)}
          className="min-h-11 rounded-lg border border-bordure-forte bg-surface px-3 text-texte"
        >
          {elements.map((element) => (
            <option key={element.id ?? "tous"} value={element.id ?? ""}>
              {element.code ? `${element.code} – ` : ""}
              {element.intitule} ({formaterNombre(element.nombre)})
            </option>
          ))}
        </select>
      </div>

      <nav
        aria-label="Filtrer par lot"
        className="hidden min-w-0 flex-[1_1_280px] flex-col gap-0.5 rounded-xl border border-bordure bg-surface p-2 lg:flex"
      >
        <h2 className="px-2.5 pt-2 pb-1.5 text-xs font-semibold uppercase tracking-[0.06em] text-attenue">Lots</h2>
        {elements.map((element) => {
          const actif = element.id === lotSelectionne;
          return (
            <button
              key={element.id ?? "tous"}
              type="button"
              aria-pressed={actif}
              onClick={() => surSelection(element.id)}
              className={`flex min-h-11 items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left leading-snug transition-colors ${
                actif ? "bg-surface-2 text-white" : "text-texte hover:bg-surface-2/60"
              }`}
            >
              {element.code && (
                <span
                  className={`w-8 shrink-0 font-titre text-xs font-semibold ${actif ? "text-accent" : "text-attenue"}`}
                >
                  {element.code}
                </span>
              )}
              <span className="min-w-0 flex-1">{element.intitule}</span>
              <span
                className={`shrink-0 rounded-full px-2 py-0.5 text-xs tabular-nums ${
                  element.nombre > 0 ? "bg-accent/15 text-accent" : "text-attenue"
                }`}
              >
                {formaterNombre(element.nombre)}
              </span>
            </button>
          );
        })}
      </nav>
    </>
  );
}
