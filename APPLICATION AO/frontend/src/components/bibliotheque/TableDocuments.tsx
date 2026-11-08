import { Download, Search, Trash2 } from "lucide-react";
import { useState } from "react";

import { api } from "../../api/client";
import type { DocumentReference, StatutAnalyse } from "../../api/types";
import { formaterDate, formaterTaille, pluriel } from "../../lib/format";

interface Proprietes {
  titre: string;
  documents: DocumentReference[] | null;
  afficherLot: boolean;
  recherche: string;
  surRecherche: (valeur: string) => void;
  surSuppression: () => void;
}

const STYLES_STATUT: Record<StatutAnalyse, string> = {
  ANALYSE: "bg-succes/12 text-succes",
  EN_ATTENTE: "bg-accent/15 text-accent",
  NON_PRIS_EN_CHARGE: "bg-info/12 text-info",
  ERREUR: "bg-danger/12 text-danger",
};

export default function TableDocuments({
  titre,
  documents,
  afficherLot,
  recherche,
  surRecherche,
  surSuppression,
}: Proprietes) {
  const [erreur, setErreur] = useState<string | null>(null);
  const [suppressionEnCours, setSuppressionEnCours] = useState<number | null>(null);

  async function supprimer(document: DocumentReference) {
    if (!window.confirm(`Supprimer définitivement « ${document.nom_original} » de la bibliothèque ?`)) return;
    setErreur(null);
    setSuppressionEnCours(document.id);
    try {
      await api(`/bibliotheque/documents/${document.id}`, { method: "DELETE" });
      surSuppression();
    } catch (probleme) {
      setErreur(probleme instanceof Error ? probleme.message : "Suppression impossible.");
    } finally {
      setSuppressionEnCours(null);
    }
  }

  return (
    <section aria-labelledby="titre-documents" className="rounded-xl border border-bordure bg-surface">
      <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
        <h2 id="titre-documents" className="font-titre text-lg font-semibold">
          {titre}
          {documents && <span className="ml-2 text-sm font-normal text-attenue">{pluriel(documents.length, "document")}</span>}
        </h2>
        <div className="relative flex-[0_1_300px]">
          <label htmlFor="recherche-documents" className="sr-only">
            Rechercher par nom de fichier ou opération
          </label>
          <Search aria-hidden="true" className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-attenue" />
          <input
            id="recherche-documents"
            type="search"
            value={recherche}
            onChange={(e) => surRecherche(e.target.value)}
            placeholder="Rechercher un fichier, une opération…"
            className="min-h-11 w-full rounded-lg border border-bordure-forte bg-fond pr-3 pl-9 text-texte"
          />
        </div>
      </div>

      {erreur && (
        <p role="alert" className="mx-5 mb-3 rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-danger">
          {erreur}
        </p>
      )}

      {documents === null ? (
        <p className="px-5 pb-6 text-attenue" role="status">
          Chargement…
        </p>
      ) : documents.length === 0 ? (
        <p className="px-5 pb-8 text-attenue">
          {recherche ? "Aucun document ne correspond à cette recherche." : "Aucun document pour l'instant. Déposez vos premiers fichiers ci-dessus."}
        </p>
      ) : (
        <div className="relative overflow-x-auto">
          <table className="w-full min-w-[720px] border-collapse">
            <thead>
              <tr className="text-left text-xs uppercase tracking-[0.06em] text-attenue">
                <th scope="col" className="px-5 py-2.5 font-semibold">Document</th>
                {afficherLot && <th scope="col" className="px-3 py-2.5 font-semibold">Lot</th>}
                <th scope="col" className="px-3 py-2.5 text-right font-semibold">Taille</th>
                <th scope="col" className="px-3 py-2.5 font-semibold">Ajouté le</th>
                <th scope="col" className="px-3 py-2.5 font-semibold">Analyse</th>
                <th scope="col" className="px-5 py-2.5 text-right font-semibold">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {documents.map((document) => {
                const details = [
                  document.operation,
                  document.annee ? String(document.annee) : "",
                  document.type_marche_libelle,
                ].filter(Boolean);
                return (
                  <tr key={document.id} className="border-t border-bordure align-top">
                    <td className="max-w-[360px] px-5 py-3">
                      <div className="flex flex-col">
                        <span className="truncate font-medium" title={document.nom_original}>
                          {document.nom_original}
                        </span>
                        {details.length > 0 && <span className="text-xs text-attenue">{details.join(" · ")}</span>}
                      </div>
                    </td>
                    {afficherLot && (
                      <td className="px-3 py-3 whitespace-nowrap">
                        {document.lot ? (
                          <span title={document.lot.intitule}>
                            <span className="font-titre font-semibold text-accent">{document.lot.code}</span>{" "}
                            <span className="text-attenue">{document.lot.intitule}</span>
                          </span>
                        ) : (
                          "—"
                        )}
                      </td>
                    )}
                    <td className="px-3 py-3 text-right whitespace-nowrap text-attenue tabular-nums">
                      {formaterTaille(document.taille)}
                    </td>
                    <td className="px-3 py-3 whitespace-nowrap text-attenue">{formaterDate(document.ajoute_le)}</td>
                    <td className="max-w-[260px] px-3 py-3">
                      <div className="flex flex-col items-start gap-1">
                        <span
                          className={`rounded-full px-2.5 py-0.5 text-xs font-semibold whitespace-nowrap ${STYLES_STATUT[document.statut_analyse]}`}
                        >
                          {document.statut_analyse_libelle}
                        </span>
                        {document.statut_analyse !== "EN_ATTENTE" && document.message_analyse && (
                          <span className="text-xs text-attenue">{document.message_analyse}</span>
                        )}
                      </div>
                    </td>
                    <td className="px-5 py-2">
                      <div className="flex justify-end gap-1">
                        <a
                          href={`/api/bibliotheque/documents/${document.id}/telecharger`}
                          aria-label={`Télécharger ${document.nom_original}`}
                          title="Télécharger"
                          className="grid size-11 place-items-center rounded-lg text-attenue hover:bg-surface-2 hover:text-texte"
                        >
                          <Download aria-hidden="true" className="size-4.5" />
                        </a>
                        <button
                          type="button"
                          onClick={() => void supprimer(document)}
                          disabled={suppressionEnCours === document.id}
                          aria-label={`Supprimer ${document.nom_original}`}
                          title="Supprimer"
                          className="grid size-11 place-items-center rounded-lg text-attenue hover:bg-danger/10 hover:text-danger disabled:opacity-40"
                        >
                          <Trash2 aria-hidden="true" className="size-4.5" />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
