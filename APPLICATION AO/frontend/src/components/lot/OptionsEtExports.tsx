import { FileDown, Trash2 } from "lucide-react";
import { useState } from "react";

import type { GenreOption, LotDetail } from "../../api/types";
import { formaterEuros } from "../../lib/format";
import { CLASSE_CHAMP } from "../Filtres";

export function OptionsLot({
  lot,
  surAjout,
  surSuppression,
  occupe,
}: {
  lot: LotDetail;
  surAjout: (genre: GenreOption, libelle: string) => Promise<void>;
  surSuppression: (id: number, nom: string) => Promise<void>;
  occupe: boolean;
}) {
  const [libelle, setLibelle] = useState("");
  const [genre, setGenre] = useState<GenreOption>("PSE");

  return (
    <section aria-labelledby="titre-options" className="flex flex-col gap-2 rounded-xl border border-bordure bg-surface p-3">
      <h2 id="titre-options" className="px-1 font-titre text-base font-semibold">
        PSE et variantes
      </h2>
      {lot.options.length === 0 ? (
        <p className="px-1 text-xs text-attenue">Aucune. Les ouvrages rattachés à une PSE sont chiffrés à part dans la DPGF.</p>
      ) : (
        <ul className="flex flex-col gap-1">
          {lot.options.map((option) => (
            <li key={option.id} className="flex items-center gap-2 rounded-lg bg-fond/40 px-2.5 py-1.5">
              <span className="min-w-0 flex-1 text-sm">
                <strong className="text-info">{option.nom_court}</strong> {option.libelle}
                <span className="block text-xs text-attenue">{formaterEuros(option.total)} HT</span>
              </span>
              <button
                type="button"
                disabled={occupe}
                onClick={() => void surSuppression(option.id, option.nom_court)}
                aria-label={`Supprimer ${option.nom_court}`}
                className="grid size-10 place-items-center rounded-lg text-attenue hover:bg-danger/10 hover:text-danger"
              >
                <Trash2 aria-hidden="true" className="size-4" />
              </button>
            </li>
          ))}
        </ul>
      )}
      <form
        className="flex flex-wrap gap-1.5"
        onSubmit={(e) => {
          e.preventDefault();
          if (!libelle.trim()) return;
          void surAjout(genre, libelle.trim()).then(() => setLibelle(""));
        }}
      >
        <label htmlFor="genre-option" className="sr-only">
          Type
        </label>
        <select id="genre-option" value={genre} onChange={(e) => setGenre(e.target.value as GenreOption)} className={`${CLASSE_CHAMP} w-auto flex-none`}>
          <option value="PSE">PSE</option>
          <option value="VARIANTE">Variante</option>
        </select>
        <label htmlFor="libelle-option" className="sr-only">
          Libellé
        </label>
        <input id="libelle-option" value={libelle} onChange={(e) => setLibelle(e.target.value)} placeholder="Ex. Volets roulants" className={`${CLASSE_CHAMP} min-w-0 flex-1`} />
        <button type="submit" disabled={occupe || !libelle.trim()} className="min-h-11 rounded-lg border border-bordure-forte px-3 text-sm font-semibold hover:bg-surface-2 disabled:opacity-50">
          Ajouter
        </button>
      </form>
    </section>
  );
}

export function Exports({ lotId, modifie }: { lotId: number; modifie: boolean }) {
  const base = `/api/lots-projet/${lotId}/export`;
  const liens = [
    { groupe: "CCTP", elements: [{ libelle: "Word", href: `${base}/cctp-docx` }, { libelle: "PDF", href: `${base}/cctp-pdf` }] },
    { groupe: "DPGF vierge (consultation)", elements: [{ libelle: "Excel", href: `${base}/dpgf-xlsx` }, { libelle: "PDF", href: `${base}/dpgf-pdf` }] },
    { groupe: "DPGF chiffrée (estimation)", elements: [{ libelle: "Excel", href: `${base}/dpgf-xlsx?prix=true` }, { libelle: "PDF", href: `${base}/dpgf-pdf?prix=true` }] },
  ];
  return (
    <section aria-labelledby="titre-exports" className="flex flex-col gap-2 rounded-xl border border-bordure bg-surface p-3">
      <h2 id="titre-exports" className="flex items-center gap-2 px-1 font-titre text-base font-semibold">
        <FileDown aria-hidden="true" className="size-4 text-accent" />
        Exporter
      </h2>
      {modifie && <p className="px-1 text-xs font-semibold text-accent">Enregistrez d'abord vos modifications : les exports utilisent la version enregistrée.</p>}
      <ul className="flex flex-col gap-1.5">
        {liens.map((ligne) => (
          <li key={ligne.groupe} className="flex flex-wrap items-center justify-between gap-2 px-1">
            <span className="text-sm">{ligne.groupe}</span>
            <span className="flex gap-1.5">
              {ligne.elements.map((lien) => (
                <a
                  key={lien.libelle}
                  href={lien.href}
                  target={lien.libelle === "PDF" ? "_blank" : undefined}
                  rel="noopener"
                  className="flex min-h-10 items-center rounded-lg border border-bordure-forte px-3 text-sm font-semibold text-texte no-underline hover:bg-surface-2"
                >
                  {lien.libelle}
                </a>
              ))}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
