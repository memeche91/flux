import { X } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router";

import type { LignePrix, Lot, PagePrix } from "../api/types";
import EnTetePage from "../components/EnTetePage";
import { BoutonAfficherPlus, CLASSE_CHAMP, Champ, ChampRecherche, delaiSaisie } from "../components/Filtres";
import { formaterEuros, formaterQuantite, origineDocument, pluriel } from "../lib/format";
import { usePagination } from "../lib/usePagination";
import { useRequete } from "../lib/useRequete";

const LIBELLES_UNITE: Record<string, string> = {
  u: "à l'unité",
  "m²": "au m²",
  "m³": "au m³",
  ml: "au mètre linéaire",
  m: "au mètre",
  ft: "au forfait",
  ens: "à l'ensemble",
  kg: "au kg",
  t: "à la tonne",
  h: "à l'heure",
  j: "à la journée",
  "—": "sans unité",
};

function libelleUnite(unite: string): string {
  return `Prix ${LIBELLES_UNITE[unite] ?? `(${unite})`}`;
}

export default function Prix() {
  const [parametres, setParametres] = useSearchParams();
  const lotId = parametres.get("lot") ?? "";
  const unite = parametres.get("unite") ?? "";
  const documentId = parametres.get("document") ?? "";
  const toutes = parametres.get("toutes") === "1";

  const [recherche, setRecherche] = useState(parametres.get("q") ?? "");
  const [rechercheAppliquee, setRechercheAppliquee] = useState(recherche);
  useEffect(() => delaiSaisie(() => setRechercheAppliquee(recherche.trim())), [recherche]);

  const modifier = (cle: string, valeur: string) => {
    const suivants = new URLSearchParams(parametres);
    if (valeur) suivants.set(cle, valeur);
    else suivants.delete(cle);
    setParametres(suivants, { replace: true });
  };

  const filtres = new URLSearchParams({ chiffrees: toutes ? "false" : "true" });
  if (lotId) filtres.set("lot_id", lotId);
  if (unite) filtres.set("unite", unite);
  if (documentId) filtres.set("document_id", documentId);
  if (rechercheAppliquee) filtres.set("recherche", rechercheAppliquee);

  const lots = useRequete<Lot[]>("/referentiel/lots");
  const liste = usePagination<LignePrix, PagePrix>(`/prix?${filtres}`);
  const statistiques = liste.donnees?.statistiques ?? [];
  const documentFiltre = documentId ? liste.elements.find((l) => String(l.document.id) === documentId)?.document : undefined;

  return (
    <>
      <EnTetePage
        surtitre="Étape 1 · Pièces écrites"
        titre="Prix de référence"
        sousTitre="Les prix unitaires relevés dans vos anciennes DPGF. Ils ne sont pas actualisés : tenez compte de l'année de chaque document."
      />

      <div className="flex flex-wrap items-end gap-3 rounded-xl border border-bordure bg-surface p-4">
        <ChampRecherche
          id="recherche-prix"
          libelle="Désignation"
          valeur={recherche}
          surChangement={setRecherche}
          indication="Ex. fenêtre aluminium, enduit, cloison…"
        />
        <Champ id="filtre-lot-prix" libelle="Lot">
          <select id="filtre-lot-prix" value={lotId} onChange={(e) => modifier("lot", e.target.value)} className={CLASSE_CHAMP}>
            <option value="">Tous les lots</option>
            {(lots.donnees ?? []).map((lot) => (
              <option key={lot.id} value={lot.id}>
                {lot.code} – {lot.intitule}
              </option>
            ))}
          </select>
        </Champ>
        <Champ id="filtre-unite" libelle="Unité">
          <select id="filtre-unite" value={unite} onChange={(e) => modifier("unite", e.target.value)} className={CLASSE_CHAMP}>
            <option value="">Toutes</option>
            {(liste.donnees?.unites ?? (unite ? [unite] : [])).map((u) => (
              <option key={u} value={u}>
                {u}
              </option>
            ))}
          </select>
        </Champ>
        <label className="flex min-h-11 flex-[1_1_200px] cursor-pointer items-center gap-2.5">
          <input
            type="checkbox"
            checked={toutes}
            onChange={(e) => modifier("toutes", e.target.checked ? "1" : "")}
            className="size-5 accent-accent"
          />
          Inclure les lignes non chiffrées
        </label>
      </div>

      {documentId && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-attenue">Document :</span>
          <span className="inline-flex items-center gap-1 rounded-full bg-surface-2 py-1 pr-1 pl-3">
            {documentFiltre?.nom_original ?? `n° ${documentId}`}
            <button
              type="button"
              onClick={() => modifier("document", "")}
              aria-label="Retirer le filtre sur ce document"
              className="grid size-8 place-items-center rounded-full hover:bg-bordure-forte"
            >
              <X aria-hidden="true" className="size-4" />
            </button>
          </span>
        </div>
      )}

      {liste.erreur && (
        <p role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-4 py-3 text-danger">
          {liste.erreur}
        </p>
      )}

      {rechercheAppliquee ? (
        statistiques.length > 0 && (
          <section aria-labelledby="titre-synthese" className="flex flex-col gap-3">
            <h2 id="titre-synthese" className="font-titre text-lg font-semibold">
              Synthèse pour « {rechercheAppliquee} »
            </h2>
            <div className="flex flex-wrap gap-3">
              {statistiques.slice(0, 4).map((s) => (
                <div key={s.unite} className="flex min-w-0 max-w-sm flex-[1_1_220px] flex-col gap-1 rounded-xl border border-bordure bg-surface px-4.5 py-4">
                  <span className="text-xs text-attenue">
                    {libelleUnite(s.unite)} · {pluriel(s.nombre, "relevé")}
                  </span>
                  <span className="font-titre text-2xl font-semibold tabular-nums">{formaterEuros(s.mediane)}</span>
                  <span className="text-xs text-attenue">
                    médiane · de {formaterEuros(s.minimum)} à {formaterEuros(s.maximum)}
                  </span>
                </div>
              ))}
            </div>
          </section>
        )
      ) : (
        <p className="text-attenue">
          Saisissez une désignation pour obtenir la médiane et la fourchette des prix relevés, par unité.
        </p>
      )}

      <section aria-labelledby="titre-lignes" className="rounded-xl border border-bordure bg-surface">
        <h2 id="titre-lignes" className="px-5 py-4 font-titre text-lg font-semibold" aria-live="polite">
          {liste.donnees ? pluriel(liste.total, "ligne de prix", "lignes de prix") : "Chargement…"}
        </h2>
        {liste.donnees && liste.total === 0 ? (
          <p className="px-5 pb-6 text-attenue">
            Aucune ligne trouvée.{" "}
            {!rechercheAppliquee && (
              <>
                Importez vos DPGF dans la{" "}
                <Link to="/bibliotheque?type=DPGF" className="text-accent">
                  bibliothèque documentaire
                </Link>
                .
              </>
            )}
          </p>
        ) : (
          <div className="relative overflow-x-auto">
            <table className="w-full min-w-[820px] border-collapse">
              <thead>
                <tr className="text-left text-xs uppercase tracking-[0.06em] text-attenue">
                  <th scope="col" className="px-5 py-2.5 font-semibold">Désignation</th>
                  <th scope="col" className="px-3 py-2.5 font-semibold">Lot</th>
                  <th scope="col" className="px-3 py-2.5 font-semibold">U</th>
                  <th scope="col" className="px-3 py-2.5 text-right font-semibold">Qté</th>
                  <th scope="col" className="px-3 py-2.5 text-right font-semibold">PU HT</th>
                  <th scope="col" className="px-5 py-2.5 font-semibold">Origine</th>
                </tr>
              </thead>
              <tbody>
                {liste.elements.map((ligne) => (
                  <tr key={ligne.id} className="border-t border-bordure align-top">
                    <td className="max-w-[420px] px-5 py-3">
                      <div className="flex flex-col">
                        {ligne.chapitre && <span className="text-xs text-attenue">{ligne.chapitre}</span>}
                        <span>
                          {ligne.numero && <span className="mr-1.5 font-titre text-attenue">{ligne.numero}</span>}
                          {ligne.designation}
                        </span>
                      </div>
                    </td>
                    <td className="px-3 py-3 whitespace-nowrap">
                      {ligne.lot ? <span className="font-titre font-semibold text-accent" title={ligne.lot.intitule}>{ligne.lot.code}</span> : "—"}
                    </td>
                    <td className="px-3 py-3 whitespace-nowrap">{ligne.unite || "—"}</td>
                    <td className="px-3 py-3 text-right whitespace-nowrap tabular-nums">{formaterQuantite(ligne.quantite)}</td>
                    <td className="px-3 py-3 text-right font-semibold whitespace-nowrap tabular-nums">{formaterEuros(ligne.prix_unitaire)}</td>
                    <td className="max-w-[240px] px-5 py-3 text-xs text-attenue">
                      <span title={ligne.document.nom_original}>{origineDocument(ligne.document)}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="flex px-5 pb-4">
          <BoutonAfficherPlus reste={liste.reste} chargement={liste.chargement} surClic={() => void liste.afficherPlus()} />
        </div>
      </section>
    </>
  );
}
