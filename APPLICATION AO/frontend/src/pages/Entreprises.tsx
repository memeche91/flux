import { Download, FileSpreadsheet, Plus, ShieldAlert } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";

import { televerser } from "../api/client";
import type { BilanImportEntreprises, EntrepriseResume, Lot } from "../api/types";
import EnTetePage from "../components/EnTetePage";
import { CLASSE_CHAMP, Champ, ChampRecherche } from "../components/Filtres";
import { pluriel } from "../lib/format";
import { useRequete } from "../lib/useRequete";

export default function Entreprises() {
  const [parametres, setParametres] = useSearchParams();
  const lotId = parametres.get("lot") ?? "";
  const actives = parametres.get("toutes") !== "1";
  const [recherche, setRecherche] = useState(parametres.get("q") ?? "");
  const [rechercheAppliquee, setRechercheAppliquee] = useState(recherche);
  useEffect(() => {
    const minuteur = window.setTimeout(() => setRechercheAppliquee(recherche.trim()), 250);
    return () => window.clearTimeout(minuteur);
  }, [recherche]);

  const requete = new URLSearchParams({ recherche: rechercheAppliquee, actives: String(actives) });
  if (lotId) requete.set("lot_id", lotId);
  const entreprises = useRequete<EntrepriseResume[]>(`/entreprises?${requete}`);
  const lots = useRequete<Lot[]>("/referentiel/lots");

  const modifier = (cle: string, valeur: string) => {
    const suivants = new URLSearchParams(parametres);
    if (valeur) suivants.set(cle, valeur);
    else suivants.delete(cle);
    setParametres(suivants, { replace: true });
  };

  return (
    <>
      <EnTetePage
        surtitre="Étape 2 · DCE"
        titre="Entreprises"
        sousTitre="Votre carnet d'adresses : spécialités par lot, contacts, qualifications et historique des consultations."
        actions={
          <>
            <a href="/api/entreprises/export" className="flex min-h-11 items-center gap-2 rounded-lg border border-bordure-forte px-3.5 text-texte no-underline hover:bg-surface-2">
              <Download aria-hidden="true" className="size-4" />
              Exporter
            </a>
            <Link to="/entreprises/nouvelle" className="flex min-h-11 items-center gap-2 rounded-lg bg-accent px-4.5 font-bold text-sur-accent no-underline hover:bg-accent-clair">
              <Plus aria-hidden="true" className="size-4" />
              Nouvelle entreprise
            </Link>
          </>
        }
      />

      <ImportAnnuaire surImporte={entreprises.recharger} />

      <div className="flex flex-wrap items-end gap-3 rounded-xl border border-bordure bg-surface p-4">
        <ChampRecherche id="recherche-entreprise" libelle="Rechercher" valeur={recherche} surChangement={setRecherche} indication="Nom, ville, savoir-faire, qualification…" />
        <Champ id="filtre-lot" libelle="Lot (spécialité)">
          <select id="filtre-lot" value={lotId} onChange={(e) => modifier("lot", e.target.value)} className={CLASSE_CHAMP}>
            <option value="">Tous les lots</option>
            {(lots.donnees ?? []).map((lot) => (
              <option key={lot.id} value={lot.id}>
                {lot.code} – {lot.intitule}
              </option>
            ))}
          </select>
        </Champ>
        <label className="flex min-h-11 items-center gap-2 text-sm text-attenue">
          <input type="checkbox" checked={!actives} onChange={(e) => modifier("toutes", e.target.checked ? "1" : "")} className="size-4 accent-[var(--color-accent)]" />
          Afficher aussi les entreprises désactivées
        </label>
      </div>

      {entreprises.erreur && (
        <p role="alert" className="rounded-lg border border-danger/40 bg-danger/10 px-4 py-3 text-danger">
          {entreprises.erreur}
        </p>
      )}
      {entreprises.donnees && (
        <p className="text-sm text-attenue" aria-live="polite">
          {pluriel(entreprises.donnees.length, "entreprise")}
        </p>
      )}
      {entreprises.donnees?.length === 0 && (
        <p className="rounded-xl border border-bordure bg-surface px-5 py-6 text-attenue">
          Aucune entreprise ne correspond. Ajoutez-en une, ou importez votre carnet d'adresses (Excel ou CSV).
        </p>
      )}

      <ul className="grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(min(100%,300px),1fr))]">
        {(entreprises.donnees ?? []).map((e) => (
          <li key={e.id}>
            <Link
              to={`/entreprises/${e.id}`}
              className={`flex h-full flex-col gap-2 rounded-xl border border-bordure bg-surface p-4 text-texte no-underline transition-colors hover:border-bordure-forte hover:bg-surface-2 ${e.actif ? "" : "opacity-60"}`}
            >
              <span className="flex items-start justify-between gap-2">
                <span className="font-titre text-base font-semibold">{e.raison_sociale}</span>
                {!e.actif && <span className="rounded-full bg-surface-2 px-2 py-0.5 text-[11px] text-attenue">Désactivée</span>}
              </span>
              <span className="text-sm text-attenue">{[e.code_postal, e.ville].filter(Boolean).join(" ") || "Ville non renseignée"}</span>
              {e.lots.length > 0 && (
                <span className="flex flex-wrap gap-1">
                  {e.lots.map((lot) => (
                    <span key={lot.id} className="rounded-md bg-accent/12 px-1.5 py-0.5 text-[11px] font-semibold text-accent" title={lot.intitule}>
                      {lot.code} {lot.intitule}
                    </span>
                  ))}
                </span>
              )}
              {e.specialites && <span className="text-xs text-attenue">{e.specialites}</span>}
              <span className="mt-auto flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-attenue">
                {e.contact_principal && <span>{e.contact_principal}</span>}
                {e.email && <span className="truncate">{e.email}</span>}
                {e.nb_consultations > 0 && <span>{pluriel(e.nb_consultations, "consultation")}</span>}
                {e.assurance_echue && (
                  <span className="flex items-center gap-1 font-semibold text-danger">
                    <ShieldAlert aria-hidden="true" className="size-3.5" />
                    Attestation d'assurance échue
                  </span>
                )}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </>
  );
}

function ImportAnnuaire({ surImporte }: { surImporte: () => void }) {
  const champ = useRef<HTMLInputElement>(null);
  const [envoi, setEnvoi] = useState(false);
  const [bilan, setBilan] = useState<BilanImportEntreprises | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);

  async function importer(fichier: File | undefined) {
    if (!fichier) return;
    setEnvoi(true);
    setErreur(null);
    setBilan(null);
    const donnees = new FormData();
    donnees.append("fichier", fichier);
    try {
      setBilan(await televerser<BilanImportEntreprises>("/entreprises/importer", donnees, () => undefined));
      surImporte();
    } catch (probleme) {
      setErreur(probleme instanceof Error ? probleme.message : "Import impossible.");
    } finally {
      setEnvoi(false);
      if (champ.current) champ.current.value = "";
    }
  }

  return (
    <section aria-labelledby="titre-import-annuaire" className="flex flex-col gap-2 rounded-xl border border-dashed border-bordure-forte bg-surface/60 px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 flex-[1_1_320px] flex-col">
          <h2 id="titre-import-annuaire" className="font-semibold">
            Importer votre carnet d'adresses
          </h2>
          <p className="text-xs text-attenue">
            Fichier Excel ou CSV : les colonnes sont reconnues (Entreprise, Ville, E-mail, Lots, Contact…). Les fiches existantes sont complétées, jamais écrasées.
          </p>
        </div>
        <label className={`flex min-h-11 cursor-pointer items-center gap-2 rounded-lg border border-bordure-forte px-3.5 font-semibold hover:bg-surface-2 ${envoi ? "opacity-50" : ""}`}>
          <FileSpreadsheet aria-hidden="true" className="size-4" />
          {envoi ? "Import en cours…" : "Choisir un fichier"}
          <input ref={champ} type="file" accept=".xlsx,.xlsm,.csv,.txt" className="sr-only" disabled={envoi} onChange={(e) => void importer(e.target.files?.[0])} />
        </label>
      </div>
      {erreur && (
        <p role="alert" className="text-danger">
          {erreur}
        </p>
      )}
      {bilan && (
        <div role="status" className="text-sm">
          <p className="text-succes">
            {pluriel(bilan.creees, "entreprise ajoutée", "entreprises ajoutées")}, {pluriel(bilan.mises_a_jour, "fiche complétée", "fiches complétées")}.
          </p>
          {bilan.ignorees.length > 0 && (
            <ul className="mt-1 list-disc pl-5 text-xs text-attenue">
              {bilan.ignorees.map((ligne) => (
                <li key={ligne}>{ligne}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
