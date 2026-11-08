import { ArrowDown, ArrowUp, FileText, Hash, Plus, Ruler, Trash2 } from "lucide-react";

import type { GenrePoste, LotDetail, Poste } from "../../api/types";
import { formaterEuros } from "../../lib/format";

interface Proprietes {
  lot: LotDetail;
  selection: number | null;
  surSelection: (id: number) => void;
  surAjout: (genre: GenrePoste) => void;
  surDeplacement: (sens: "haut" | "bas") => void;
  surSuppression: () => void;
  occupe: boolean;
}

const ICONES: Record<GenrePoste, typeof Hash> = { CHAPITRE: Hash, ARTICLE: FileText, OUVRAGE: Ruler };

export default function PlanLot({ lot, selection, surSelection, surAjout, surDeplacement, surSuppression, occupe }: Proprietes) {
  const options = new Map(lot.options.map((o) => [o.id, o]));
  const selectionne = lot.postes.find((p) => p.id === selection);

  return (
    <section aria-labelledby="titre-plan" className="flex flex-col gap-2 rounded-xl border border-bordure bg-surface p-3">
      <div className="flex items-center justify-between gap-2 px-1">
        <h2 id="titre-plan" className="font-titre text-base font-semibold">
          Plan du lot
        </h2>
        <span className="text-xs text-attenue">Base : {formaterEuros(lot.total_base)} HT</span>
      </div>

      <div className="flex flex-wrap gap-1" role="group" aria-label="Ajouter après la sélection">
        {(
          [
            ["CHAPITRE", "Chapitre"],
            ["ARTICLE", "Article"],
            ["OUVRAGE", "Ouvrage"],
          ] as [GenrePoste, string][]
        ).map(([genre, libelle]) => (
          <button
            key={genre}
            type="button"
            disabled={occupe}
            onClick={() => surAjout(genre)}
            className="flex min-h-10 flex-1 items-center justify-center gap-1.5 rounded-lg border border-bordure-forte px-2 text-xs font-semibold hover:bg-surface-2 disabled:opacity-50"
          >
            <Plus aria-hidden="true" className="size-3.5" />
            {libelle}
          </button>
        ))}
      </div>

      <ol className="flex max-h-[62vh] flex-col overflow-y-auto" aria-label="Éléments du lot">
        {lot.postes.map((poste) => (
          <li key={poste.id}>
            <LignePlan poste={poste} actif={poste.id === selection} mention={poste.option_id ? options.get(poste.option_id)?.nom_court : undefined} surClic={() => surSelection(poste.id)} />
          </li>
        ))}
      </ol>

      {selectionne && (
        <div className="flex items-center justify-between gap-1 border-t border-bordure pt-2" role="group" aria-label="Élément sélectionné">
          <span className="truncate px-1 text-xs text-attenue">{selectionne.numero}</span>
          <div className="flex gap-1">
            <BoutonIcone libelle="Monter" desactive={occupe} surClic={() => surDeplacement("haut")}>
              <ArrowUp className="size-4" />
            </BoutonIcone>
            <BoutonIcone libelle="Descendre" desactive={occupe} surClic={() => surDeplacement("bas")}>
              <ArrowDown className="size-4" />
            </BoutonIcone>
            <BoutonIcone libelle="Supprimer" desactive={occupe} surClic={surSuppression} danger>
              <Trash2 className="size-4" />
            </BoutonIcone>
          </div>
        </div>
      )}
    </section>
  );
}

function LignePlan({ poste, actif, mention, surClic }: { poste: Poste; actif: boolean; mention?: string; surClic: () => void }) {
  const Icone = ICONES[poste.genre];
  const chapitre = poste.genre === "CHAPITRE";
  return (
    <button
      type="button"
      onClick={surClic}
      aria-current={actif ? "true" : undefined}
      className={`flex min-h-10 w-full items-start gap-2 rounded-lg px-2 py-1.5 text-left transition-colors ${
        actif ? "bg-accent/15 text-white ring-1 ring-accent/60" : "hover:bg-surface-2"
      } ${chapitre ? "mt-1.5 font-semibold" : "pl-5"}`}
    >
      <Icone aria-hidden="true" className={`mt-0.5 size-3.5 shrink-0 ${chapitre ? "text-accent" : "text-attenue"}`} />
      <span className={`shrink-0 font-titre text-xs leading-5 ${chapitre ? "text-accent" : "text-attenue"}`}>{poste.numero}</span>
      <span className="min-w-0 flex-1 leading-5">
        {poste.titre}
        {mention && <span className="ml-1.5 rounded bg-info/15 px-1.5 text-[11px] font-semibold text-info">{mention}</span>}
      </span>
      {poste.montant != null && <span className="shrink-0 text-xs leading-5 text-attenue tabular-nums">{formaterEuros(poste.montant)}</span>}
    </button>
  );
}

function BoutonIcone({ libelle, surClic, desactive, danger = false, children }: { libelle: string; surClic: () => void; desactive: boolean; danger?: boolean; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-label={libelle}
      title={libelle}
      onClick={surClic}
      disabled={desactive}
      className={`grid size-10 place-items-center rounded-lg disabled:opacity-40 ${danger ? "text-attenue hover:bg-danger/10 hover:text-danger" : "text-attenue hover:bg-surface-2 hover:text-texte"}`}
    >
      {children}
    </button>
  );
}
