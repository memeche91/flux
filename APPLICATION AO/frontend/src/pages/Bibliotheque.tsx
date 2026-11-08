import { useEffect, useState } from "react";
import { useSearchParams } from "react-router";

import { TYPES_DOCUMENT, type DocumentReference, type Lot, type Statistiques } from "../api/types";
import EnTetePage from "../components/EnTetePage";
import ListeLots from "../components/bibliotheque/ListeLots";
import TableDocuments from "../components/bibliotheque/TableDocuments";
import ZoneImport from "../components/bibliotheque/ZoneImport";
import { formaterNombre } from "../lib/format";
import { useRequete } from "../lib/useRequete";

export default function Bibliotheque() {
  const [parametres, setParametres] = useSearchParams();
  const type = TYPES_DOCUMENT.find((t) => t.code === parametres.get("type")) ?? TYPES_DOCUMENT[0];
  const lotSelectionne = type.parLot ? Number(parametres.get("lot")) || null : null;

  const [recherche, setRecherche] = useState("");
  const [rechercheAppliquee, setRechercheAppliquee] = useState("");
  useEffect(() => {
    const minuterie = window.setTimeout(() => setRechercheAppliquee(recherche.trim()), 250);
    return () => window.clearTimeout(minuterie);
  }, [recherche]);

  const filtres = new URLSearchParams({ type_document: type.code });
  if (lotSelectionne) filtres.set("lot_id", String(lotSelectionne));
  if (rechercheAppliquee) filtres.set("recherche", rechercheAppliquee);

  const lots = useRequete<Lot[]>("/referentiel/lots");
  const stats = useRequete<Statistiques>("/bibliotheque/statistiques");
  const documents = useRequete<DocumentReference[]>(`/bibliotheque/documents?${filtres}`);
  const rechargerDocuments = documents.recharger;
  const rechargerStats = stats.recharger;

  // Tant qu'une analyse est en cours, on rafraîchit la liste toutes les 3 secondes.
  const analyseEnCours = documents.donnees?.some((d) => d.statut_analyse === "EN_ATTENTE") ?? false;
  useEffect(() => {
    if (!analyseEnCours) return;
    const minuterie = window.setInterval(rechargerDocuments, 3000);
    return () => window.clearInterval(minuterie);
  }, [analyseEnCours, rechargerDocuments]);

  const rafraichir = () => {
    rechargerDocuments();
    rechargerStats();
  };

  const choisirType = (code: string) => {
    setRecherche("");
    setParametres({ type: code });
  };
  const choisirLot = (lotId: number | null) =>
    setParametres(lotId ? { type: type.code, lot: String(lotId) } : { type: type.code });

  const lotActif = lots.donnees?.find((l) => l.id === lotSelectionne);
  const erreur = lots.erreur ?? stats.erreur ?? documents.erreur;

  return (
    <>
      <EnTetePage
        surtitre="Étape 1 · Pièces écrites"
        titre="Bibliothèque documentaire"
        sousTitre="Vos anciens CCAP, actes d'engagement, règlements de consultation, CCTP et DPGF. Ils serviront à reproduire votre style de rédaction et vos prix."
      />

      <div role="tablist" aria-label="Type de document" className="flex flex-wrap gap-1 border-b border-bordure">
        {TYPES_DOCUMENT.map((t) => {
          const actif = t.code === type.code;
          return (
            <button
              key={t.code}
              role="tab"
              type="button"
              aria-selected={actif}
              onClick={() => choisirType(t.code)}
              className={`-mb-px flex min-h-11 items-center gap-2 border-b-2 px-4 font-semibold transition-colors ${
                actif ? "border-accent text-white" : "border-transparent text-attenue hover:text-texte"
              }`}
            >
              {t.libelle}
              <span
                className={`rounded-full px-2 py-0.5 text-xs tabular-nums ${
                  actif ? "bg-accent text-sur-accent" : "bg-surface-2 text-attenue"
                }`}
              >
                {stats.donnees ? formaterNombre(stats.donnees.par_type[t.code]) : "·"}
              </span>
            </button>
          );
        })}
      </div>

      <p className="-mt-2 text-attenue">{type.description}.</p>

      {erreur && (
        <p role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-4 py-3 text-danger">
          {erreur}
        </p>
      )}

      <div className="flex flex-wrap items-start gap-5">
        {type.parLot && (
          <ListeLots
            lots={lots.donnees ?? []}
            comptes={stats.donnees?.par_lot[type.code as "CCTP" | "DPGF"] ?? {}}
            lotSelectionne={lotSelectionne}
            surSelection={choisirLot}
          />
        )}
        <div className="flex min-w-0 flex-[999_1_560px] flex-col gap-5">
          <ZoneImport
            type={type}
            lots={lots.donnees ?? []}
            lotSelectionne={lotSelectionne}
            surDocumentAjoute={rafraichir}
          />
          <TableDocuments
            titre={lotActif ? `${type.libelle} · lot ${lotActif.code} – ${lotActif.intitule}` : type.pluriel}
            documents={documents.donnees}
            afficherLot={type.parLot && !lotSelectionne}
            recherche={recherche}
            surRecherche={setRecherche}
            surSuppression={rafraichir}
          />
        </div>
      </div>
    </>
  );
}
